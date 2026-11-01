"""Run N4/N5 over stored N0-N3 results. No model calls, no production writes.

    python tools/run_n4_n5.py --fixture data/claim-pipeline/n2n3-fixtures.json --limit 2
    python tools/run_n4_n5.py --limit 20
    python tools/run_n4.py --fixture ... --limit 2
    python tools/run_n5.py --fixture ... --limit 2

N2/N3 are looked up in the append-only store using the same model metadata the Batch 9
runner recorded. If a node is missing the article is reported as missing, not recomputed with
a model.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from opportunity_radar import (n2_semantic, n3_relationships, n4_normalization,
                               n5_assembly, semantic_common)  # noqa: E402
from opportunity_radar.config import Settings  # noqa: E402
from opportunity_radar.pipeline_store import PipelineStore  # noqa: E402
from tools.run_n1 import prepare_document  # noqa: E402
from tools.run_n2_n3 import fixture_articles, fetch_pool  # noqa: E402

DEFAULT_STORE = ROOT / 'data' / 'claim-pipeline' / 'node_runs.sqlite3'


def _node_params(node, max_tokens):
    return {'node': node, 'temperature': 0.0, 'max_tokens': int(max_tokens),
            'response_format': 'json_schema'}


def _find(store, article_id, node, version, input_hash, params):
    if store is None:
        return None
    return store.find(article_id, node, version, input_hash, params)


def _record(store, article_id, document, node, version, input_hash, output, params, tools):
    if store is None:
        return
    store.record(article_id=article_id, document_id=document.get('document_id', ''),
                 content_hash=document.get('content_hash', ''), node_name=node,
                 node_version=version, input_hash=input_hash, output=output,
                 params=params, tools=tools)


def summarise(records, seconds):
    n4_records = [record['n4'] for record in records if record.get('n4')]
    n5_records = [record['n5'] for record in records if record.get('n5')]
    n4_by_status, n5_dispositions, n5_reasons = {}, {}, {}
    for output in n4_records:
        for status, count in (output.get('statistics', {}).get('by_status') or {}).items():
            n4_by_status[status] = n4_by_status.get(status, 0) + count
    for output in n5_records:
        for status, count in (output.get('coverage_statistics', {})
                              .get('disposition_counts') or {}).items():
            n5_dispositions[status] = n5_dispositions.get(status, 0) + count
        for item in output.get('rejected_items') or []:
            n5_reasons[item.get('reason', '')] = n5_reasons.get(item.get('reason', ''), 0) + 1
        for item in output.get('unresolved_items') or []:
            n5_reasons[item.get('reason', '')] = n5_reasons.get(item.get('reason', ''), 0) + 1
    return {
        'articles': len(records), 'seconds': round(seconds, 1),
        'n4': {
            'articles': len(n4_records),
            'claim_values': sum(output.get('statistics', {}).get('claim_values', 0)
                                for output in n4_records),
            'records': sum(output.get('statistics', {}).get('records', 0)
                           for output in n4_records),
            'by_status': n4_by_status,
            'failed_articles': sum(1 for output in n4_records
                                   if output.get('status') not in ('success', 'partial')),
            'reused': sum(1 for record in records if record.get('n4_reused')),
            'seconds': round(sum(output.get('seconds', 0) for output in n4_records), 1),
        },
        'n5': {
            'articles': len(n5_records),
            'claims': sum(len(output.get('claims') or []) for output in n5_records),
            'claim_values': sum(output.get('coverage_statistics', {}).get('claim_value_total', 0)
                                for output in n5_records),
            'dispositions': n5_dispositions,
            'reasons': dict(sorted(n5_reasons.items(), key=lambda item: -item[1])),
            'coverage_complete': all(output.get('coverage_statistics', {})
                                     .get('coverage_complete') for output in n5_records),
            'contract_valid': all(output.get('contract_validation', {}).get('valid')
                                  for output in n5_records),
            'failed_articles': sum(1 for output in n5_records
                                   if output.get('status') not in
                                   ('success', 'partial', 'blocked')),
            'reused': sum(1 for record in records if record.get('n5_reused')),
            'seconds': round(sum(output.get('seconds', 0) for output in n5_records), 1),
        },
        'missing': {
            'n2': sum(1 for record in records if record.get('missing') == 'n2'),
            'n3': sum(1 for record in records if record.get('missing') == 'n3'),
        },
        'errors': [{'article_id': record['article_id'], 'error': record['error']}
                   for record in records if record.get('error')],
    }


def render(summary):
    n4, n5 = summary['n4'], summary['n5']
    lines = [
        '# N4 + N5 标准化与 Claim 组装', '',
        f"- 文章：{summary['articles']}；总耗时：{summary['seconds']} 秒", '',
        '## N4', '', '| 指标 | 数值 |', '|---|---:|',
        f"| 文章 | {n4['articles']} |",
        f"| claim_value | {n4['claim_values']} |",
        f"| 标准化记录 | {n4['records']} |",
        f"| 缓存复用 | {n4['reused']} |",
        f"| 失败文章 | {n4['failed_articles']} |",
        f"| 耗时 | {n4['seconds']} 秒 |", '',
        '记录状态：' + json.dumps(n4['by_status'], ensure_ascii=False), '',
        '## N5', '', '| 指标 | 数值 |', '|---|---:|',
        f"| 文章 | {n5['articles']} |",
        f"| claim_value | {n5['claim_values']} |",
        f"| 合格影子 Claim | {n5['claims']} |",
        f"| 覆盖完整 | {n5['coverage_complete']} |",
        f"| 契约校验通过 | {n5['contract_valid']} |",
        f"| 缓存复用 | {n5['reused']} |",
        f"| 失败文章 | {n5['failed_articles']} |",
        f"| 耗时 | {n5['seconds']} 秒 |", '',
        '候选处置：' + json.dumps(n5['dispositions'], ensure_ascii=False), '',
        '不能生成 Claim/未处理原因：' + json.dumps(n5['reasons'], ensure_ascii=False), '',
        f"缺失 N2：{summary['missing']['n2']}；缺失 N3：{summary['missing']['n3']}",
    ]
    if summary['errors']:
        lines += ['', '## 失败', '']
        lines += [f"- {item['article_id']}: {item['error'][:160]}" for item in summary['errors']]
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run N4/N5 over stored N0-N3 results')
    parser.add_argument('--nodes', default='both', choices=['n4', 'n5', 'both'])
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--article-id', action='append', default=[])
    parser.add_argument('--sources', default='')
    parser.add_argument('--urls-file', default='')
    parser.add_argument('--per-source', type=int, default=0)
    parser.add_argument('--fixture', default='')
    parser.add_argument('--out', '--output-dir', dest='out', default='')
    parser.add_argument('--store', default=str(DEFAULT_STORE))
    parser.add_argument('--no-store', action='store_true')
    parser.add_argument('--no-reuse', action='store_true')
    parser.add_argument('--n2-tokens', type=int, default=1600)
    parser.add_argument('--n3-tokens', type=int, default=1400)
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
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    out_dir = Path(args.out or ROOT / 'data' / 'claim-pipeline' / f'n4n5-{stamp}')
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    records = []
    with (out_dir / 'n4n5.jsonl').open('w', encoding='utf-8') as stream:
        for index, article in enumerate(articles, 1):
            record = {'n': index, 'article_id': article.article_id, 'title': article.title,
                      'source': article.source_name, 'url': article.url}
            article_started = time.time()
            try:
                _text, document, n1, _n1_reused = prepare_document(article, store)
                record['n1_statistics'] = n1.get('statistics')
                n2_model = semantic_common.model_metadata(settings, args.n2_tokens, True)
                n2 = _find(store, article.article_id, 'N2', n2_semantic.NODE_VERSION,
                           n2_semantic.input_hash(document, n1, n2_model),
                           _node_params('N2', args.n2_tokens))
                if n2 is None:
                    record['missing'] = 'n2'
                    record['error'] = 'N2 result not found in the store'
                    records.append(record)
                    stream.write(json.dumps(record, ensure_ascii=False) + '\n')
                    print(f"[{index}/{len(articles)}] {article.title[:50]} · N2 missing",
                          flush=True)
                    continue
                n3_model = semantic_common.model_metadata(settings, args.n3_tokens, True)
                n3 = _find(store, article.article_id, 'N3', n3_relationships.NODE_VERSION,
                           n3_relationships.input_hash(document, n1, n2, n3_model),
                           _node_params('N3', args.n3_tokens))
                if n3 is None:
                    record['missing'] = 'n3'
                    record['error'] = 'N3 result not found in the store'
                    records.append(record)
                    stream.write(json.dumps(record, ensure_ascii=False) + '\n')
                    print(f"[{index}/{len(articles)}] {article.title[:50]} · N3 missing",
                          flush=True)
                    continue
                record['n2'], record['n3'] = n2, n3
                n4 = None
                if args.nodes in ('n4', 'both'):
                    n4_model = {'node': 'N4', 'version': n4_normalization.NODE_VERSION,
                                'units_version': n4_normalization.UNITS_VERSION}
                    n4_hash = n4_normalization.input_hash(document, n1, n2, n3)
                    n4 = None if args.no_reuse else _find(
                        store, article.article_id, 'N4', n4_normalization.NODE_VERSION,
                        n4_hash, {'node': 'N4'})
                    if n4 is not None:
                        record['n4_reused'] = True
                    else:
                        n4 = n4_normalization.normalize(document, n1, n2, n3)
                        record['n4_reused'] = False
                        _record(store, article.article_id, document, 'N4',
                                n4_normalization.NODE_VERSION, n4_hash, n4,
                                {'node': 'N4'}, {'units_version': n4_normalization.UNITS_VERSION})
                    record['n4'] = n4
                elif args.nodes == 'n5':
                    n4_hash = n4_normalization.input_hash(document, n1, n2, n3)
                    n4 = _find(store, article.article_id, 'N4', n4_normalization.NODE_VERSION,
                               n4_hash, {'node': 'N4'})
                    if n4 is None:
                        record['missing'] = 'n4'
                        record['error'] = 'N4 result not found in the store'
                        records.append(record)
                        stream.write(json.dumps(record, ensure_ascii=False) + '\n')
                        print(f"[{index}/{len(articles)}] {article.title[:50]} · N4 missing",
                              flush=True)
                        continue
                    record['n4'], record['n4_reused'] = n4, True
                if args.nodes in ('n5', 'both') and n4 is not None:
                    n5_hash = n5_assembly.input_hash(document, n1, n2, n3, n4)
                    n5 = None if args.no_reuse else _find(
                        store, article.article_id, 'N5', n5_assembly.NODE_VERSION,
                        n5_hash, {'node': 'N5'})
                    if n5 is not None:
                        record['n5_reused'] = True
                    else:
                        n5 = n5_assembly.assemble(document, n1, n2, n3, n4)
                        record['n5_reused'] = False
                        _record(store, article.article_id, document, 'N5',
                                n5_assembly.NODE_VERSION, n5_hash, n5,
                                {'node': 'N5'},
                                {'contract_version': n5_assembly.CONTRACT_VERSION,
                                 'contract_hash': n5_assembly.CONTRACT_HASH})
                    record['n5'] = n5
                record['seconds'] = round(time.time() - article_started, 2)
            except Exception as exc:  # one article must not stop the run
                record['error'] = f'{type(exc).__name__}: {exc}'[:300]
                record['seconds'] = round(time.time() - article_started, 2)
            records.append(record)
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
            stream.flush()
            print(f"[{index}/{len(articles)}] {article.title[:50]} · "
                  f"N4={record.get('n4', {}).get('status', '-') if record.get('n4') else '-'} "
                  f"N5={record.get('n5', {}).get('status', '-') if record.get('n5') else '-'} "
                  f"· {record['seconds']}s", flush=True)
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
