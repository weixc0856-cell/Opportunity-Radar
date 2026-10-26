#!/usr/bin/env python3
"""Run the fixed 28-item pool through the real model with the v5 prompt.

This is an offline verification tool, not part of the daily pipeline:
  * it never opens the production SQLite database;
  * it uses the production prompt, parser, evaluator and lane rules;
  * results are appended to a JSON file so a long run can resume in batches.

Usage:
    python tools/run_pool_v5.py --max-seconds 420
    python tools/run_pool_v5.py --report-only
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from opportunity_radar.analyzer import LocalAnalyzer, PROMPT_HASH, PROMPT_VERSION  # noqa: E402
from opportunity_radar.cli import evaluate, resolve_source, source_index  # noqa: E402
from opportunity_radar.config import Settings, load_scoring  # noqa: E402
from opportunity_radar.schema import parse_model_json  # noqa: E402
from opportunity_radar.source_policy import load_sources  # noqa: E402

DEFAULT_POOL = ROOT / 'data' / 'actionability-experiment-2026-10-23' / 'pool.json'
DEFAULT_OUT = ROOT / 'data' / 'pool-v5-20261026'


class MeasuringAnalyzer(LocalAnalyzer):
    """The production analyzer, plus per-call usage, latency and finish_reason."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = []

    def _call(self, messages, max_tokens=None):
        body = {'model': self.model, 'temperature': 0.2, 'max_tokens': max_tokens or self.max_tokens,
                'messages': messages, 'chat_template_kwargs': {'enable_thinking': False}}
        request = urllib.request.Request(self.url, data=json.dumps(body).encode(),
                                         headers=self._headers(), method='POST')
        record = {'max_tokens': max_tokens or self.max_tokens}
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode('utf-8', 'replace'))
        except Exception as exc:
            record.update({'elapsed': round(time.perf_counter() - started, 2), 'error': f'{type(exc).__name__}: {exc}',
                           'usage': {}, 'finish_reason': '', 'content_chars': 0})
            self.calls.append(record)
            raise
        choice = (data.get('choices') or [{}])[0]
        content = (choice.get('message') or {}).get('content') or ''
        usage = data.get('usage') or {}
        record.update({
            'elapsed': round(time.perf_counter() - started, 2),
            'error': '',
            'usage': {'prompt_tokens': usage.get('prompt_tokens'),
                      'completion_tokens': usage.get('completion_tokens'),
                      'total_tokens': usage.get('total_tokens')},
            'finish_reason': choice.get('finish_reason') or '',
            'content_chars': len(content),
        })
        self.calls.append(record)
        return content


def article_of(item):
    return SimpleNamespace(title=item['title'], summary=item['summary'], url=item['url'],
                           source_name=item.get('source_name', ''), published=item.get('published', ''),
                           feed_id='', content_source='rss_summary', retrieval_status='ok', article_id='')


def article_dict(item):
    return {'title': item['title'], 'summary': item['summary'], 'url': item['url'],
            'published': item.get('published', '')}


def load_results(path):
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding='utf-8'))


def save_results(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + '\n', encoding='utf-8', newline='\n')
    tmp.replace(path)


def run_item(item, settings, source, lanes):
    analyzer = MeasuringAnalyzer(settings.llm_base_url, settings.llm_model, settings.llm_timeout,
                                 settings.llm_max_tokens, api_key=settings.llm_api_key)
    trace = []
    started = time.perf_counter()
    analysis = None
    error = ''
    try:
        analysis = analyzer.analyze(item['title'], item['summary'], item.get('source_name', ''),
                                    item['url'], trace=trace)
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    wall = round(time.perf_counter() - started, 2)

    first_error = ''
    if trace:
        try:
            parse_model_json(trace[0], article_dict(item))
        except Exception as exc:
            first_error = f'{type(exc).__name__}: {exc}'

    row = {
        'item_id': item['item_id'], 'title': item['title'], 'source_name': item.get('source_name', ''),
        'source_id': item.get('source_id', ''), 'label': item.get('label', ''),
        'ok': analysis is not None, 'error': error, 'wall_seconds': wall,
        'calls': analyzer.calls, 'retried': len(analyzer.calls) > 1,
        'first_parse_error': first_error, 'raw': trace,
    }
    if analysis is None:
        return row

    row['schema_version'] = analysis.get('schema_version')
    facts = analysis.get('facts') or []
    inferences = analysis.get('inferences') or []
    gaps = analysis.get('gaps') or []
    actions = analysis.get('actions') or []
    located = [f for f in facts if f.get('status') == 'located']
    unlocated = [f for f in facts if f.get('status') != 'located']
    row.update({
        'facts_total': len(facts), 'facts_located': len(located), 'facts_unlocated': len(unlocated),
        'facts_missing_quote': sum(1 for f in facts if f.get('reason') == 'missing_quote'),
        'facts_quote_not_found': sum(1 for f in facts if f.get('reason') == 'quote_not_in_text'),
        'inferences_supported': sum(1 for i in inferences if i.get('status') == 'supported'),
        'inferences_unsupported': sum(1 for i in inferences if i.get('status') != 'supported'),
        'gaps': len(gaps), 'actions': len(actions),
        'evidence_quotes': len(analysis.get('evidence_quotes') or []),
        'schema_deviations': len(analysis.get('schema_deviations') or []),
    })
    item_record = evaluate(article_of(item), analysis, model=settings.llm_model, source=source,
                           lanes_config=lanes)
    row.update({
        'score': item_record.get('score'), 'status': item_record.get('status'),
        'filter_reason': item_record.get('filter_reason', ''), 'lane': item_record.get('lane'),
        'evidence_rank': item_record.get('evidence_rank'), 'evidence_state': item_record.get('evidence_state'),
        'degraded_all_unlocated': bool(facts) and not located and not analysis.get('evidence_quotes'),
        'no_facts': not facts,
    })
    return row


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def aggregate(rows):
    done = [r for r in rows]
    ok = [r for r in done if r['ok']]
    v5 = [r for r in ok if r.get('schema_version') == 5]
    v4 = [r for r in ok if r.get('schema_version') == 4]
    failed = [r for r in done if not r['ok']]
    retried = [r for r in done if r['retried']]
    calls = [c for r in done for c in r['calls']]
    usage_calls = [c for c in calls if (c.get('usage') or {}).get('total_tokens') is not None]
    latencies = [c['elapsed'] for c in calls if c.get('elapsed') is not None]
    walls = [r['wall_seconds'] for r in done]
    facts_total = sum(r.get('facts_total', 0) for r in ok)
    facts_located = sum(r.get('facts_located', 0) for r in ok)
    facts_unlocated = sum(r.get('facts_unlocated', 0) for r in ok)
    degraded = [r for r in ok if r.get('degraded_all_unlocated')]
    no_facts = [r for r in ok if r.get('no_facts')]
    filtered_evidence = [r for r in ok if r.get('filter_reason') == 'insufficient_evidence']
    length_first = [r for r in done if any(c.get('finish_reason') == 'length' for c in r['calls'][:1])]
    return {
        'done': len(done), 'ok': len(ok), 'v5': len(v5), 'v4_fallback': len(v4), 'failed': len(failed),
        'retried': len(retried), 'retry_succeeded': sum(1 for r in retried if r['ok']),
        'retry_failed': sum(1 for r in retried if not r['ok']),
        'first_call_length': len(length_first),
        'calls': len(calls), 'calls_with_usage': len(usage_calls),
        'latency_mean': round(statistics.mean(latencies), 2) if latencies else None,
        'latency_median': round(statistics.median(latencies), 2) if latencies else None,
        'latency_p95': percentile([round(x, 2) for x in latencies], 0.95),
        'latency_max': max(latencies) if latencies else None,
        'wall_mean': round(statistics.mean(walls), 2) if walls else None,
        'wall_total': round(sum(walls), 1),
        'prompt_tokens': sum(c['usage']['prompt_tokens'] for c in usage_calls),
        'completion_tokens': sum(c['usage']['completion_tokens'] for c in usage_calls),
        'total_tokens': sum(c['usage']['total_tokens'] for c in usage_calls),
        'facts_total': facts_total, 'facts_located': facts_located, 'facts_unlocated': facts_unlocated,
        'located_ratio': round(facts_located / facts_total, 3) if facts_total else None,
        'facts_missing_quote': sum(r.get('facts_missing_quote', 0) for r in ok),
        'facts_quote_not_found': sum(r.get('facts_quote_not_found', 0) for r in ok),
        'inferences_supported': sum(r.get('inferences_supported', 0) for r in ok),
        'inferences_unsupported': sum(r.get('inferences_unsupported', 0) for r in ok),
        'degraded_all_unlocated': len(degraded),
        'no_facts': len(no_facts),
        'filtered_insufficient_evidence': len(filtered_evidence),
        'degraded_ids': [r['item_id'] for r in degraded],
        'no_fact_ids': [r['item_id'] for r in no_facts],
        'failed_ids': [r['item_id'] for r in failed],
        'retry_ids': [r['item_id'] for r in retried],
        'length_ids': [r['item_id'] for r in length_first],
    }


def report(rows, pool_size, out_dir, settings):
    a = aggregate(rows)
    lines = [
        '# v5 固定池运行报告', '',
        f'- 时间：{datetime.now().astimezone().isoformat(timespec="seconds")}',
        f'- 模型：`{settings.llm_model}`',
        f'- 提示词：v{PROMPT_VERSION}（`{PROMPT_HASH}`）· 规则 v5 · 池 {pool_size} 条',
        f'- 已完成：{a["done"]} / {pool_size}；剩余：{max(0, pool_size - a["done"])}',
        '', '## 一、成功率与重试', '',
        f'- 成功：{a["ok"]}（v5 {a["v5"]} · v4 兼容回落 {a["v4_fallback"]}）· 失败：{a["failed"]}',
        f'- 触发重试：{a["retried"]}（重试成功 {a["retry_succeeded"]} · 重试仍失败 {a["retry_failed"]}）',
        f'- 首次调用 `finish_reason=length`：{a["first_call_length"]}（{", ".join(a["length_ids"]) or "无"}）',
        f'- 失败条目：{", ".join(a["failed_ids"]) or "无"}',
        f'- 重试条目：{", ".join(a["retry_ids"]) or "无"}',
        '', '## 二、事实定位', '',
        f'- facts 总数：{a["facts_total"]}；located {a["facts_located"]}；unlocated {a["facts_unlocated"]}'
        f'（定位率 {a["located_ratio"] if a["located_ratio"] is not None else "n/a"}）',
        f'- unlocated 细分：missing_quote {a["facts_missing_quote"]} · quote_not_in_text {a["facts_quote_not_found"]}',
        f'- 推断：supported {a["inferences_supported"]} · unsupported {a["inferences_unsupported"]}',
        '', '## 三、降级', '',
        f'- facts 全部未定位 → evidence_quotes 为空：{a["degraded_all_unlocated"]}（{", ".join(a["degraded_ids"]) or "无"}）',
        f'- 没有 facts：{a["no_facts"]}（{", ".join(a["no_fact_ids"]) or "无"}）',
        f'- 最终因 `insufficient_evidence` 被过滤：{a["filtered_insufficient_evidence"]}',
        '', '## 四、耗时与 Token', '',
        f'- 调用数：{a["calls"]}（其中带 usage：{a["calls_with_usage"]}）',
        f'- 单次延迟：平均 {a["latency_mean"]}s · 中位 {a["latency_median"]}s · p95 {a["latency_p95"]}s · 最长 {a["latency_max"]}s',
        f'- 单条耗时：平均 {a["wall_mean"]}s · 总计 {a["wall_total"]}s',
        f'- Token：prompt {a["prompt_tokens"]} · completion {a["completion_tokens"]} · total {a["total_tokens"]}',
    ]
    if a['calls_with_usage']:
        lines.append(f'- 每条平均 token：{round(a["total_tokens"] / a["calls_with_usage"], 1)}（按调用）'
                     f' · {round(a["total_tokens"] / max(1, a["done"]), 1)}（按条目）')
    else:
        lines.append('- Token：服务端未返回 usage，无法统计。')
    failures = [r for r in rows if not r['ok'] or r.get('schema_version') != 5 or r.get('facts_unlocated')]
    if failures:
        lines += ['', '## 五、需要人工看的条目', '', '| item | 状态 | 原因 |', '|---|---|---|']
        for r in failures:
            reason = r.get('error') or r.get('first_parse_error') or (
                f"v4 回落" if r.get('schema_version') == 4 else
                f"facts 未定位 {r.get('facts_unlocated')}/{r.get('facts_total')}")
            lines.append(f"| {r['item_id']} | {'ok' if r['ok'] else 'fail'} | {reason} |")
    text = '\n'.join(lines) + '\n'
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'report.md').write_text(text, encoding='utf-8', newline='\n')
    (out_dir / 'report.json').write_text(
        json.dumps({'aggregate': a, 'prompt_version': PROMPT_VERSION, 'prompt_hash': PROMPT_HASH,
                    'model': settings.llm_model}, ensure_ascii=False, indent=1) + '\n',
        encoding='utf-8', newline='\n')
    return text


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description='Run the fixed pool through the real model with prompt v5')
    parser.add_argument('--pool', type=Path, default=DEFAULT_POOL)
    parser.add_argument('--out-dir', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--max-items', type=int, default=0, help='0 = all remaining')
    parser.add_argument('--max-seconds', type=float, default=0, help='0 = no time budget')
    parser.add_argument('--report-only', action='store_true')
    parser.add_argument('--fresh', action='store_true', help='delete previous results in the out dir')
    args = parser.parse_args(argv)

    pool = json.loads(args.pool.read_text(encoding='utf-8'))
    results_path = args.out_dir / 'results.json'
    if args.fresh and results_path.exists():
        results_path.unlink()
    rows = load_results(results_path)
    settings = Settings.from_env()

    if not args.report_only:
        sources = {s.source_id: s for s in load_sources()}
        by_id, by_name, _ = source_index(list(sources.values()))
        lanes = load_scoring().get('lanes')
        done = {r['item_id'] for r in rows}
        started = time.perf_counter()
        attempted = 0
        for item in pool:
            if item['item_id'] in done:
                continue
            if args.max_items and attempted >= args.max_items:
                break
            if args.max_seconds and time.perf_counter() - started >= args.max_seconds:
                print(f'time budget reached after {attempted} item(s)', flush=True)
                break
            source = sources.get(item.get('source_id', '')) or resolve_source(item, by_id, by_name)
            item_started = time.perf_counter()
            row = run_item(item, settings, source, lanes)
            rows.append(row)
            attempted += 1
            save_results(results_path, rows)
            print(f"[{len(rows)}/{len(pool)}] {item['item_id']} ok={row['ok']} "
                  f"v{row.get('schema_version', '?')} facts={row.get('facts_total', 0)}/"
                  f"{row.get('facts_located', 0)} retried={row['retried']} "
                  f"{row.get('wall_seconds')}s", flush=True)
            if time.perf_counter() - item_started > 180:
                print('  (slow item; consider stopping after this batch)', flush=True)
        if not attempted:
            print('nothing to do; use --fresh to start over', flush=True)

    print(report(load_results(results_path), len(pool), args.out_dir, settings))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
