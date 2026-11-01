"""Run N0 + N1 over the FreshRSS pool and report what the numerical scan found.

Read-only: this tool never writes to the production database and never calls the model. It
fetches the articles FreshRSS serves, normalises each one with N0, scans it with N1, and
writes the candidates to JSON so the next node can be developed against a fixed input.

    python tools/run_n1.py --limit 50
    python tools/run_n1.py --benchmark data/r2-shadow/benchmark.json

With `--benchmark` it also scores the scan against a hand-annotated set of numbers. That
score is the point of N1: it measures whether the deterministic scan finds the figures the
model was missing, independently of any model output.
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

from opportunity_radar import article_text, numeric_candidates, units  # noqa: E402
from opportunity_radar.config import Settings  # noqa: E402
from opportunity_radar.freshrss_client import FreshRSSClient, ordered_feed_ids  # noqa: E402
from opportunity_radar.source_policy import is_approved, load_sources  # noqa: E402


def fetch_pool(settings, limit, sources='', urls_file='', per_source=0):
    client = FreshRSSClient(settings.freshrss_base_url, settings.freshrss_username,
                            settings.freshrss_api_key, settings.request_timeout)
    approved = {source.freshrss_feed_id for source in load_sources() if is_approved(source)}
    articles = client.fetch_articles(max(limit, 400), feed_ids=ordered_feed_ids(approved))
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


def scan_article(article, index):
    started = time.time()
    record = {'n': index, 'url': article.url, 'title': article.title,
              'source': article.source_name}
    try:
        text = article_text.build(article)
        result = numeric_candidates.extract(text)
        record.update({
            'ok': True, 'text_hash': text.text_hash, 'source_hash': text.source_hash,
            'n0': text.to_dict()['stats'], 'stats': result['stats'],
            'candidates': result['candidates'],
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
        return candidate['category'] == 'percent' and units.same_number(
            value, candidate.get('value'))
    if unit.startswith('usd'):
        return (candidate['category'] == 'money' and candidate.get('currency') == 'USD'
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
            matched.append(number)
        matched_total += len(matched)
        per_article.append({
            'title': article['title'], 'url': article['url'],
            'found': record is not None,
            'annotated': len(article.get('numbers', [])),
            'matched': len(matched), 'missing': missing,
            'candidates': len(candidates),
        })
    return {'annotated': total, 'matched': matched_total,
            'recall': round(matched_total / total, 3) if total else None,
            'unsupported_annotations': unsupported, 'articles': per_article}


def summarise(records, seconds, bench=None):
    ok = [record for record in records if record.get('ok')]
    by_category, per_article = {}, []
    digits = covered = 0
    uncovered = []
    for record in ok:
        stats = record['stats']
        per_article.append(stats['total'])
        for category, count in stats['by_category'].items():
            by_category[category] = by_category.get(category, 0) + count
        digits += stats['coverage']['digits']
        covered += stats['coverage']['covered']
        if stats['coverage']['uncovered']:
            uncovered.append({'title': record['title'],
                              'uncovered': stats['coverage']['uncovered'][:5]})
    total = sum(per_article)
    return {
        'articles': len(records), 'scanned': len(ok), 'failed': len(records) - len(ok),
        'candidates': total,
        'candidates_per_article': round(total / len(ok), 2) if ok else 0,
        'by_category': dict(sorted(by_category.items(), key=lambda item: -item[1])),
        'digits': digits, 'covered': covered,
        'coverage_complete': covered == digits and not uncovered,
        'uncovered': uncovered,
        'articles_without_candidates': sum(1 for count in per_article if count == 0),
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
        f"- 候选：{summary['candidates']} 条（每篇 {summary['candidates_per_article']}）",
        f"- 无候选文章：{summary['articles_without_candidates']} 篇",
        f"- 数字字符覆盖：{summary['covered']}/{summary['digits']}"
        f"（{'完整' if summary['coverage_complete'] else '**有遗漏，见下**'}）",
        f"- 耗时：{summary['seconds']} 秒", '',
        '## 按类别', '',
        '| 类别 | 条数 |', '|---|---|',
    ]
    for category, count in summary['by_category'].items():
        lines.append(f'| {category} | {count} |')
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
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run N0 (normalise) + N1 (numeric scan)')
    parser.add_argument('--limit', type=int, default=50)
    parser.add_argument('--per-source', type=int, default=0)
    parser.add_argument('--sources', default='', help='comma separated source_name filter')
    parser.add_argument('--urls-file', default='', help='scan exactly these URLs')
    parser.add_argument('--benchmark', default='', help='hand-annotated numbers to score against')
    parser.add_argument('--out', default='')
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    articles = fetch_pool(settings, args.limit, args.sources, args.urls_file, args.per_source)
    if not articles:
        print('no article in the FreshRSS pool matched; nothing to scan', file=sys.stderr)
        return 2

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    out_dir = Path(args.out or ROOT / 'data' / 'claim-pipeline' / stamp)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    records = []
    with (out_dir / 'n1.jsonl').open('w', encoding='utf-8') as stream:
        for index, article in enumerate(articles, 1):
            record = scan_article(article, index)
            records.append(record)
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
            stream.flush()
            count = record.get('stats', {}).get('total', '-')
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
