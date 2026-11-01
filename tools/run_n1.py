"""Run N0 + N1 over the FreshRSS pool and report what the numerical scan found.

Read-only for the production database and the model: this tool fetches the articles FreshRSS
serves, normalises each one with N0, scans it with N1, records both node runs in a separate
append-only SQLite file (`data/claim-pipeline/node_runs.sqlite3` by default), and writes the
candidates to JSON.

    python tools/run_n1.py --limit 50
    python tools/run_n1.py --benchmark data/r2-shadow/benchmark.json

The body is requested with `max_content=0`: N0 must see the whole body FreshRSS holds, not
the production analyzer's 12,000-character window. With `--benchmark` the scan is also scored
against a hand-annotated set of numbers, independently of any model output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from opportunity_radar import article_text, numeric_candidates, units  # noqa: E402
from opportunity_radar.config import Settings  # noqa: E402
from opportunity_radar.freshrss_client import FreshRSSClient, ordered_feed_ids  # noqa: E402
from opportunity_radar.pipeline_store import PipelineStore  # noqa: E402
from opportunity_radar.source_policy import is_approved, load_sources  # noqa: E402

DEFAULT_STORE = ROOT / 'data' / 'claim-pipeline' / 'node_runs.sqlite3'
TOOLS = {'rules': numeric_candidates.VERSION, 'ruleset': numeric_candidates.RULESET,
         'recognizers_text': 'not_installed'}


def fetch_pool(settings, limit, sources='', urls_file='', per_source=0):
    client = FreshRSSClient(settings.freshrss_base_url, settings.freshrss_username,
                            settings.freshrss_api_key, settings.request_timeout)
    approved = {source.freshrss_feed_id for source in load_sources() if is_approved(source)}
    # 0 means no cap: the analyzer's window is a production choice, not N0's input limit.
    articles = client.fetch_articles(max(limit, 400), feed_ids=ordered_feed_ids(approved),
                                     max_content=0)
    seen, unique = set(), []
    for article in articles:
        if article.url in seen:
            continue
        seen.add(article.url)
        unique.append(article)
    if urls_file:
        wanted = {line.strip() for line in Path(urls_file).read_text(encoding='utf-8').splitlines()
                  if line.strip()}
        unique = [article for article in unique if article.url in wanted]
    if sources:
        allowed = {name.strip() for name in sources.split(',') if name.strip()}
        unique = [article for article in unique if article.source_name in allowed]
    if per_source:
        used, balanced = {}, []
        for article in unique:
            if used.get(article.source_name, 0) >= per_source:
                continue
            used[article.source_name] = used.get(article.source_name, 0) + 1
            balanced.append(article)
        unique = balanced
    return unique[:limit]


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True)
                          .encode('utf-8')).hexdigest()


def scan_article(article, index, store=None):
    started = time.time()
    article_id = article.article_id or article.url
    payload = {
        'article_id': article_id,
        'source_id': article.feed_id or article.source_name,
        'title': article.title,
        'content': article.summary,
        'content_format': 'html',
        'source_url': article.url,
    }
    record = {'n': index, 'url': article.url, 'title': article.title,
              'source': article.source_name, 'article_id': article_id}
    try:
        text = article_text.build(payload)
        document = text.to_dict()
        input_hash = _hash({'title': payload['title'], 'content': payload['content'],
                            'content_format': payload['content_format'],
                            'version': article_text.VERSION,
                            'ruleset': article_text.RULESET})
        if store is not None:
            store.record(article_id=article_id, document_id=text.document_id,
                         content_hash=text.content_hash, node_name='N0',
                         node_version=article_text.VERSION, input_hash=input_hash,
                         output=document,
                         params={'content_format': 'html', 'ruleset': article_text.RULESET},
                         tools={'python': 'stdlib'})
        n1_input = _hash({'document_id': text.document_id, 'text_hash': text.text_hash,
                          'paragraphs': len(text.paragraphs),
                          'sentences': len(text.sentences),
                          'version': article_text.VERSION,
                          'ruleset': numeric_candidates.RULESET})
        cached = None
        if store is not None:
            cached = store.find(article_id, 'N1', numeric_candidates.VERSION, n1_input,
                                {'recognizers': 'off',
                                 'ruleset': numeric_candidates.RULESET})
        if cached is not None:
            result = cached
        else:
            result = numeric_candidates.extract(text)
            if store is not None:
                store.record(article_id=article_id, document_id=text.document_id,
                             content_hash=text.content_hash, node_name='N1',
                             node_version=numeric_candidates.VERSION, input_hash=n1_input,
                             output=result,
                             params={'recognizers': 'off',
                                     'ruleset': numeric_candidates.RULESET},
                             tools=TOOLS)
        record.update({
            'ok': True,
            'document_id': text.document_id,
            'content_hash': text.content_hash,
            'text_hash': text.text_hash,
            'n0': document['stats'],
            'content_truncated': document['content_truncated'],
            'n1_reused': cached is not None,
            'statistics': result['statistics'],
            'candidates': result['candidates'],
            'expression_groups': result['expression_groups'],
            'seconds': round(time.time() - started, 3),
        })
    except Exception as exc:  # one failed article must not stop the scan
        record.update({'ok': False, 'error': f'{type(exc).__name__}: {exc}'[:300],
                       'seconds': round(time.time() - started, 3)})
    return record


def _annotation_scale(unit):
    for word, factor in units.SCALES:
        if word in unit.split():
            return units.scale_name(factor)
    return ''


def candidate_matches(annotation, candidate):
    """Whether one candidate satisfies one hand annotation. Unsupported units return None."""
    unit = str(annotation.get('unit') or '').strip().lower()
    value = annotation.get('value')
    if unit in ('%', 'percent', 'per cent'):
        return (candidate['candidate_type'] == 'percentage'
                and units.same_number(value, candidate.get('value')))
    if unit.startswith('usd'):
        return (candidate['candidate_type'] == 'currency'
                and candidate.get('currency') == 'USD'
                and candidate.get('scale') == _annotation_scale(unit)
                and units.same_number(value, candidate.get('value')))
    return None


def benchmark(annotations, records):
    """One-to-one recall of the annotated numbers against the candidates of each article."""
    by_url = {record['url']: record for record in records}
    per_article, unsupported = [], 0
    total = matched_total = 0
    for article in annotations:
        record = by_url.get(article['url'])
        candidates = record.get('candidates', []) if record else []
        used, matched, missing = set(), [], []
        for number in article.get('numbers', []):
            total += 1
            hit = None
            for index, candidate in enumerate(candidates):
                if index in used:
                    continue
                verdict = candidate_matches(number, candidate)
                if verdict is None:
                    unsupported += 1
                    break
                if verdict:
                    hit = index
                    break
            if hit is None:
                missing.append(number)
                continue
            used.add(hit)
            candidate = candidates[hit]
            matched.append(dict(number, candidate_id=candidate['candidate_id'],
                                raw_text=candidate['raw_text'],
                                start=candidate['start'], end=candidate['end'],
                                sentence_id=candidate['sentence_id'],
                                paragraph_id=candidate['paragraph_id']))
        matched_total += len(matched)
        per_article.append({
            'title': article['title'], 'url': article['url'],
            'found': record is not None,
            'annotated': len(article.get('numbers', [])),
            'matched': len(matched), 'missing': missing, 'matches': matched,
            'candidates': len(candidates),
        })
    return {'annotated': total, 'matched': matched_total,
            'recall': round(matched_total / total, 3) if total else None,
            'unsupported_annotations': unsupported, 'articles': per_article}


def summarise(records, seconds, bench=None):
    ok = [record for record in records if record.get('ok')]
    by_type, per_article = {}, []
    digits = covered = groups = 0
    uncovered, reused = [], 0
    for record in ok:
        statistics = record['statistics']
        per_article.append(statistics['candidate_count'])
        for candidate_type, count in statistics['by_type'].items():
            by_type[candidate_type] = by_type.get(candidate_type, 0) + count
        digits += statistics['coverage']['digits']
        covered += statistics['coverage']['covered']
        groups += statistics['expression_group_count']
        reused += 1 if record.get('n1_reused') else 0
        if statistics['coverage']['uncovered']:
            uncovered.append({'title': record['title'],
                              'uncovered': statistics['coverage']['uncovered'][:5]})
    total = sum(per_article)
    return {
        'articles': len(records), 'scanned': len(ok), 'failed': len(records) - len(ok),
        'candidates': total,
        'candidates_per_article': round(total / len(ok), 2) if ok else 0,
        'expression_groups': groups,
        'by_type': dict(sorted(by_type.items(), key=lambda item: -item[1])),
        'unclassified_numeric': by_type.get('unclassified_numeric', 0),
        'digits': digits, 'covered': covered,
        'coverage_complete': covered == digits and not uncovered,
        'uncovered': uncovered,
        'articles_without_candidates': sum(1 for count in per_article if count == 0),
        'truncated_articles': sum(1 for record in ok if record.get('content_truncated')),
        'reused_runs': reused,
        'seconds': round(seconds, 2),
        'failures': [{'n': record['n'], 'title': record['title'][:60],
                      'error': record.get('error', '')}
                     for record in records if not record.get('ok')],
        'benchmark': bench,
    }


def render(summary):
    lines = [
        '# N0 + N1 数字候选扫描', '',
        f"- 文章：{summary['articles']} 篇，成功 {summary['scanned']}，失败 {summary['failed']}",
        f"- 原子候选：{summary['candidates']} 条（每篇 {summary['candidates_per_article']}）",
        f"- 复合表达：{summary['expression_groups']} 组；未分类数字：{summary['unclassified_numeric']}",
        f"- 无候选文章：{summary['articles_without_candidates']} 篇",
        f"- 数字字符覆盖：{summary['covered']}/{summary['digits']}"
        f"（{'完整' if summary['coverage_complete'] else '**有遗漏，见下**'}）",
        f"- 正文被截断：{summary['truncated_articles']} 篇；复用历史 N1 结果：{summary['reused_runs']} 篇",
        f"- 耗时：{summary['seconds']} 秒", '',
        '## 原子候选类型', '',
        '| 类型 | 条数 |', '|---|---|',
    ]
    for candidate_type, count in summary['by_type'].items():
        lines.append(f'| {candidate_type} | {count} |')
    if summary['uncovered']:
        lines += ['', '## 未被候选覆盖的数字（应为空）', '']
        for item in summary['uncovered']:
            lines.append(f"- {item['title'][:60]}: {item['uncovered']}")
    if summary['benchmark']:
        bench = summary['benchmark']
        lines += ['', '## 人工基准召回', '',
                  f"- 标注 {bench['annotated']} 个，命中 {bench['matched']} 个，"
                  f"召回 {bench['recall']}",
                  f"- 无法比对的口径：{bench['unsupported_annotations']}", '',
                  '| 文章 | 标注 | 命中 | 遗漏 |', '|---|---|---|---|']
        for article in bench['articles']:
            missing = '、'.join(f"{n['value']}{n['unit']}" for n in article['missing']) or '—'
            found = '' if article['found'] else '（池中未找到）'
            lines.append(f"| {article['title'][:48]}{found} | {article['annotated']} | "
                         f"{article['matched']} | {missing} |")
        located = [match for article in bench['articles'] for match in article['matches']]
        if located:
            lines += ['', '### 命中位置', '',
                      '| 数值 | 原文 | 位置 | 句子 | 段落 |', '|---|---|---|---|---|']
            for match in located:
                lines.append(f"| {match['value']}{match['unit']} | {match['raw_text']} | "
                             f"{match['start']}-{match['end']} | {match['sentence_id']} | "
                             f"{match['paragraph_id']} |")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run N0 (normalise) + N1 (numeric scan)')
    parser.add_argument('--limit', type=int, default=50)
    parser.add_argument('--per-source', type=int, default=0)
    parser.add_argument('--sources', default='', help='comma separated source_name filter')
    parser.add_argument('--urls-file', default='', help='scan exactly these URLs')
    parser.add_argument('--benchmark', default='', help='hand-annotated numbers to score against')
    parser.add_argument('--out', default='')
    parser.add_argument('--store', default=str(DEFAULT_STORE), help='append-only node-run store')
    parser.add_argument('--no-store', action='store_true', help='do not record or reuse runs')
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    articles = fetch_pool(settings, args.limit, args.sources, args.urls_file, args.per_source)
    if not articles:
        print('no article in the FreshRSS pool matched; nothing to scan', file=sys.stderr)
        return 2

    store = None if args.no_store else PipelineStore(args.store)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    out_dir = Path(args.out or ROOT / 'data' / 'claim-pipeline' / stamp)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    records = []
    with (out_dir / 'n1.jsonl').open('w', encoding='utf-8') as stream:
        for index, article in enumerate(articles, 1):
            record = scan_article(article, index, store)
            records.append(record)
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
            stream.flush()
            count = record.get('statistics', {}).get('candidate_count', '-')
            print(f"[{index}/{len(articles)}] {article.title[:60]} · "
                  f"candidates={count} · {record['seconds']}s", flush=True)
    seconds = time.time() - started

    bench = None
    if args.benchmark:
        annotations = json.loads(Path(args.benchmark).read_text(encoding='utf-8'))
        bench = benchmark(annotations, records)
    summary = summarise(records, seconds, bench)
    (out_dir / 'summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (out_dir / 'summary.md').write_text(render(summary), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f'written to {out_dir}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
