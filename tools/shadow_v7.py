"""Shadow-run the v7 prompt (structured claims) against the v6 analyses already stored.

It never touches the production database or the production prompt: articles come from FreshRSS,
the comparison comes from a copy of the stored v6 analysis, and everything lands as JSON under
`data/r2-shadow/`.

    python tools/shadow_v7.py --limit 8 --db data/opportunity_radar.sqlite3

Per article it records what the article section produced under each prompt, then the v7 claims
with their field completeness, quote location and contract deviations.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from opportunity_radar import claim_contract, schema  # noqa: E402
from opportunity_radar.analyzer import LocalAnalyzer  # noqa: E402
from opportunity_radar.config import Settings, parse_backoff  # noqa: E402
from opportunity_radar.freshrss_client import FreshRSSClient, ordered_feed_ids  # noqa: E402
from opportunity_radar.source_policy import is_approved, load_sources  # noqa: E402


def load_v7_system():
    """The v7 text plus the shared rules, composed exactly as the production loader does."""
    path = ROOT / 'prompts' / 'analyst_v7.md'
    lines = path.read_text(encoding='utf-8').splitlines()
    version = '1'
    if lines and lines[0].upper().startswith('VERSION:'):
        version = lines[0].split(':', 1)[1].strip()
        lines = lines[1:]
    text = '\n'.join(lines).strip()
    for name in ('output_contract.md', 'style_guide_zh.md'):
        shared = ROOT / 'prompts' / 'shared' / name
        if shared.exists():
            text += '\n\n' + shared.read_text(encoding='utf-8').strip()
    return version, text


def stored_analyses(db):
    conn = sqlite3.connect('file:' + str(db) + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        out = {}
        for row in conn.execute('SELECT a.url, a.title, s.result_json FROM articles a JOIN analyses s USING(article_key)'):
            try:
                out[row['url']] = json.loads(row['result_json'])
            except ValueError:
                continue
        return out
    finally:
        conn.close()


def pool(settings, limit):
    client = FreshRSSClient(settings.freshrss_base_url, settings.freshrss_username,
                            settings.freshrss_api_key, settings.request_timeout)
    approved = {s.freshrss_feed_id for s in load_sources() if is_approved(s)}
    return client.fetch_articles(max(limit * 8, 40), feed_ids=ordered_feed_ids(approved))


def claim_metrics(claims, article, deviations):
    located = 0
    complete = 0
    fields = {'value': 0, 'unit': 0, 'period': 0, 'comparison': 0, 'kind': 0}
    for claim in claims:
        locator = schema._locate(claim.get('quote') or '', article.get('title', ''), article.get('summary', ''))
        if locator:
            located += 1
        if claim.get('value_num') is not None:
            fields['value'] += 1
        if claim.get('unit'):
            fields['unit'] += 1
        if claim.get('period'):
            fields['period'] += 1
        if (claim.get('comparison') or 'unknown') != 'unknown':
            fields['comparison'] += 1
        if (claim.get('kind') or 'unknown') != 'unknown':
            fields['kind'] += 1
        if claim.get('value_num') is not None and claim.get('unit') and claim.get('period'):
            complete += 1
    return {
        'claims': len(claims),
        'quotes_located': located,
        'value_num': fields['value'],
        'with_unit': fields['unit'],
        'with_period': fields['period'],
        'with_comparison': fields['comparison'],
        'with_kind': fields['kind'],
        'structured_complete': complete,
        'deviations': deviations,
        'units': sorted({c.get('unit') or '' for c in claims if c.get('unit')}),
        'kinds': sorted({c.get('kind') or 'unknown' for c in claims}),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description='Shadow-run prompt v7 against stored v6 analyses')
    parser.add_argument('--limit', type=int, default=8)
    parser.add_argument('--db', default='data/opportunity_radar.sqlite3')
    parser.add_argument('--out', default='')
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    version, system = load_v7_system()
    stored = stored_analyses(args.db)
    client_pool = pool(settings, args.limit)
    candidates = [a for a in client_pool if a.url in stored][:args.limit]
    if not candidates:
        print('no article in the FreshRSS pool has a stored v6 analysis; nothing to compare', file=sys.stderr)
        return 2

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    out_dir = Path(args.out or ROOT / 'data' / 'r2-shadow' / stamp)
    out_dir.mkdir(parents=True, exist_ok=True)
    stream = (out_dir / 'v7.jsonl').open('w', encoding='utf-8')

    analyzer = LocalAnalyzer(settings.llm_base_url, settings.llm_model, settings.llm_timeout,
                             max(settings.llm_max_tokens, 1600), api_key=settings.llm_api_key,
                             connect_retries=settings.llm_connect_retries,
                             timeout_retries=settings.llm_timeout_retries,
                             backoff=parse_backoff(settings.llm_retry_backoff),
                             retry_after_max=settings.llm_retry_after_max,
                             retry_max_seconds=settings.llm_retry_max_seconds, system=system)

    rows = []
    for index, article in enumerate(candidates, 1):
        started = time.time()
        record = {'n': index, 'url': article.url, 'title': article.title, 'source': article.source_name,
                  'prompt_version': version}
        try:
            raw = analyzer._call([{'role': 'system', 'content': system},
                                  {'role': 'user', 'content': json.dumps(
                                      {'source_name': article.source_name, 'title': article.title[:1000],
                                       'summary': article.summary[:7000], 'url': article.url,
                                       'task': 'Analyze this article for potential commercial opportunity signals.'},
                                      ensure_ascii=False)}])
            parsed = schema.parse_model_json(raw, {'title': article.title, 'summary': article.summary,
                                                   'url': article.url,
                                                   'published': getattr(article, 'published', '')})
            raw_claims = parsed.get('claims') or []
            claims, deviations = claim_contract.parse_claims({'claims': raw_claims})
            record.update({'ok': True, 'v7_facts': len(parsed.get('facts') or []),
                           'v7_located': sum(1 for f in parsed.get('facts') or [] if f.get('status') == 'located'),
                           'v7_inferences': len(parsed.get('inferences') or []),
                           'claims': claim_metrics(claims, {'title': article.title, 'summary': article.summary}, deviations),
                           # The claims themselves, so field accuracy can be judged, not just counted.
                           'claim_items': [dict(item, quote_located=bool(schema._locate(
                               item.get('quote') or '', article.title, article.summary))) for item in claims]})
        except Exception as exc:  # a failed shadow article must not stop the run
            record.update({'ok': False, 'error': f'{type(exc).__name__}: {exc}'[:300]})
        v6 = stored.get(article.url) or {}
        analysis6 = v6.get('analysis') or {}
        record['v6'] = {'schema_version': analysis6.get('schema_version'),
                        'facts': len(analysis6.get('facts') or []),
                        'located': sum(1 for f in analysis6.get('facts') or [] if f.get('status') == 'located'),
                        'inferences': len(analysis6.get('inferences') or [])}
        record['seconds'] = round(time.time() - started, 1)
        rows.append(record)
        stream.write(json.dumps(record, ensure_ascii=False) + '\n')
        stream.flush()
        print(f"[{index}/{len(candidates)}] {article.title[:60]} · {record.get('seconds')}s · "
              f"v7 claims={record.get('claims', {}).get('claims', '-')}", flush=True)
    stream.close()

    summary = summarise(rows, version)
    (out_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (out_dir / 'summary.md').write_text(render(summary), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f'written to {out_dir}')
    return 0


def summarise(rows, version):
    ok = [r for r in rows if r.get('ok')]
    claims = [r['claims'] for r in ok]
    deviations = {}
    for c in claims:
        for d in c['deviations']:
            key = f"{d['field']}:{d['reason']}"
            deviations[key] = deviations.get(key, 0) + 1
    total_claims = sum(c['claims'] for c in claims)
    return {
        'prompt_version': version,
        'articles': len(rows),
        'analysed': len(ok),
        'failed': len(rows) - len(ok),
        'v6_facts': sum(r['v6']['facts'] for r in rows),
        'v6_located': sum(r['v6']['located'] for r in rows),
        'v7_facts': sum(r.get('v7_facts', 0) for r in ok),
        'v7_located': sum(r.get('v7_located', 0) for r in ok),
        'claims': total_claims,
        'claims_per_article': round(total_claims / len(ok), 2) if ok else 0,
        'claims_quotes_located': sum(c['quotes_located'] for c in claims),
        'claims_with_value': sum(c['value_num'] for c in claims),
        'claims_with_unit': sum(c['with_unit'] for c in claims),
        'claims_with_period': sum(c['with_period'] for c in claims),
        'claims_with_comparison': sum(c['with_comparison'] for c in claims),
        'claims_structured_complete': sum(c['structured_complete'] for c in claims),
        'deviations': dict(sorted(deviations.items(), key=lambda kv: -kv[1])),
        'deviations_total': sum(deviations.values()),
        'units': sorted({u for c in claims for u in c['units']}),
        'kinds': sorted({k for c in claims for k in c['kinds']}),
        'seconds_total': round(sum(r.get('seconds', 0) for r in rows), 1),
    }


def render(summary):
    lines = [
        f"# v7 影子运行（{summary['prompt_version']}）", '',
        f"- 文章：{summary['articles']} 篇，成功 {summary['analysed']}，失败 {summary['failed']}",
        f"- 耗时：{summary['seconds_total']} 秒",
        '', '## 与 v6 对照', '',
        '| 项 | v6 | v7 |', '|---|---|---|',
        f"| 事实条数 | {summary['v6_facts']} | {summary['v7_facts']} |",
        f"| 可定位引文 | {summary['v6_located']} | {summary['v7_located']} |",
        '', '## v7 结构化主张', '',
        f"- 主张总数：{summary['claims']}（每篇 {summary['claims_per_article']}）",
        f"- 引文可定位：{summary['claims_quotes_located']}",
        f"- 带数值：{summary['claims_with_value']}",
        f"- 带单位：{summary['claims_with_unit']}",
        f"- 带期间：{summary['claims_with_period']}",
        f"- 带比较口径：{summary['claims_with_comparison']}",
        f"- 数值+单位+期间齐全：{summary['claims_structured_complete']}",
        f"- 契约偏差：{summary['deviations_total']} {summary['deviations']}",
        f"- 出现过的单位：{summary['units']}",
        f"- 出现过的类型：{summary['kinds']}",
    ]
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    raise SystemExit(main())
