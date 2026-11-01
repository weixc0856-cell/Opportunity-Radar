"""Analyse a v7 shadow run: field completeness, missed numbers, verification outcomes.

    python tools/shadow_analyse.py data/r2-shadow/<stamp>

Reads the run's `v7.jsonl`, stores the claims in a scratch copy of the production database,
verifies them there, and writes `analysis.md` next to the run. Nothing touches production.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from opportunity_radar import units, verify  # noqa: E402
from opportunity_radar.config import Settings  # noqa: E402
from opportunity_radar.freshrss_client import FreshRSSClient, ordered_feed_ids  # noqa: E402
from opportunity_radar.source_policy import is_approved, load_sources  # noqa: E402
from opportunity_radar.unified import UnifiedStore, now, stable_id  # noqa: E402

PRODUCTION = ROOT / 'data' / 'opportunity_radar.sqlite3'


def article_texts(urls):
    """url -> summary, re-read from FreshRSS. The runner deliberately does not store article
    bodies, so the analysis asks the feed again instead of keeping a copy."""
    settings = Settings.from_env()
    client = FreshRSSClient(settings.freshrss_base_url, settings.freshrss_username,
                            settings.freshrss_api_key, settings.request_timeout)
    approved = {s.freshrss_feed_id for s in load_sources() if is_approved(s)}
    try:
        pool = client.fetch_articles(400, feed_ids=ordered_feed_ids(approved))
    except Exception:
        return {}
    wanted = set(urls)
    return {a.url: (a.summary or '') for a in pool if a.url in wanted}


def key_numbers(text):
    """Numbers in the article that carry a unit - the ones a reader would expect to see."""
    return [(value, unit) for value, unit in units.quantities(text) if unit]


def load(run_dir):
    path = Path(run_dir) / 'v7.jsonl'
    return [json.loads(line) for line in path.open(encoding='utf-8')]


def store_claims(records):
    """Write the shadow claims into a scratch database so the real verifier can judge them."""
    scratch = Path(records[0]['_scratch']) if records and '_scratch' in records[0] else None
    target = scratch or (Path(ROOT) / 'data' / 'r2-shadow' / 'analysis.sqlite3')
    shutil.copy2(PRODUCTION, target)
    store = UnifiedStore(str(target))
    inserted = 0
    for record in records:
        for index, claim in enumerate(record.get('claim_items') or [], 1):
            key = 'shadow-%s-%s' % (record['n'], index)
            evidence = {
                'evidence_id': stable_id('ev-', key), 'article_key': '', 'source_id': record['source'],
                'evidence_kind': 'quote', 'quote': claim.get('quote') or '',
                'locator_json': json.dumps({'field': 'summary'}), 'source_family': record['source'],
                'independence': 'unknown', 'observed_at': None, 'rules_version': 'r2-v1',
                'created_at': now(),
            }
            row = {
                'claim_id': stable_id('cl-', key), 'article_key': '', 'event_id': None, 'fact_ordinal': index,
                'subject': claim.get('subject') or '', 'predicate': claim.get('predicate') or '',
                'value_num': claim.get('value_num'), 'value_text': claim.get('value_text') or '',
                'unit': claim.get('unit') or '', 'unit_raw': claim.get('unit_raw') or '',
                'currency': claim.get('currency') or '', 'region': claim.get('region') or '',
                'period': claim.get('period') or '', 'period_raw': claim.get('period_raw') or '',
                'comparison': claim.get('comparison') or 'unknown', 'denominator': '',
                'seasonality': claim.get('seasonality') or 'unknown',
                'revision': claim.get('revision') or 'unknown', 'revision_raw': claim.get('revision_raw') or '',
                'kind': claim.get('kind') or 'unknown', 'quote': claim.get('quote') or '',
                'locator_json': '{}', 'verification_state': 'unverified', 'extractor': 'structured',
                'rules_version': 'r2-v1', 'created_at': now(),
            }
            store.add_evidence(evidence)
            store.add_claim(row)
            store.link(row['claim_id'], evidence['evidence_id'])
            inserted += 1
    return store, target, inserted


def analyse(run_dir):
    records = load(run_dir)
    ok = [r for r in records if r.get('ok')]
    claims = [c for r in ok for c in (r.get('claim_items') or [])]
    texts = article_texts([r['url'] for r in ok])
    key = [n for r in ok for n in key_numbers(texts.get(r['url'], ''))]
    missing_text = [r['n'] for r in ok if r['url'] not in texts]
    covered = 0
    for value, unit in key:
        if any(c.get('value_num') is not None and units.same_number(
                c['value_num'] * units.split_unit(c.get('unit'))[1], value) for c in claims):
            covered += 1
    fields = {'value': 0, 'unit': 0, 'period': 0, 'comparison': 0, 'quote': 0}
    for c in claims:
        if c.get('value_num') is not None: fields['value'] += 1
        if c.get('unit'): fields['unit'] += 1
        if c.get('period'): fields['period'] += 1
        if (c.get('comparison') or 'unknown') != 'unknown': fields['comparison'] += 1
        if c.get('quote_located'): fields['quote'] += 1
    kinds = Counter(c.get('kind') or 'unknown' for c in claims)

    store, scratch, inserted = store_claims(records)
    report = verify.verify(store)
    audit = verify.audit(store)
    with store.connect() as conn:
        states = {r[0]: r[1] for r in conn.execute(
            "SELECT verification_state, COUNT(*) FROM claims WHERE extractor='structured' GROUP BY 1")}
    return records, ok, claims, key, covered, fields, kinds, inserted, report, audit, states, scratch, missing_text


def render(run_dir, data):
    (records, ok, claims, key, covered, fields, kinds, inserted, report, audit, states, scratch,
     missing_text) = data
    total = len(claims)
    pct = (lambda n: f'{n}（{n * 100 // total}%）') if total else (lambda n: str(n))
    lines = [
        '# v7 影子运行分析', '',
        f'- 运行目录：`{run_dir}`',
        f'- 文章：{len(records)} 篇，成功 {len(ok)}，失败 {len(records) - len(ok)}',
        f'- 主张：{total} 条，写入临时库 {inserted} 条（`{scratch}`）',
        '', '## 字段完整率', '',
        '| 字段 | 有条数 |', '|---|---|',
        f"| 数值 | {pct(fields['value'])} |",
        f"| 单位 | {pct(fields['unit'])} |",
        f"| 期间 | {pct(fields['period'])} |",
        f"| 比较口径 | {pct(fields['comparison'])} |",
        f"| 引文可定位 | {pct(fields['quote'])} |",
        '', '## 关键数字覆盖', '',
        f"- 正文中带单位的数字：{len(key)} 个；被主张覆盖：{covered}"
        + (f"（{covered * 100 // len(key)}%）" if key else ''),
        (f"- 有 {len(missing_text)} 篇已不在 FreshRSS 池中，未计入关键数字统计：{missing_text}"
         if missing_text else ''),
        '', '## 核验结果（仅影子主张）', '',
        f'- 状态：{states}',
        f'- 支持关系：{report["by_support"]}',
        '', '## 检查执行情况', '',
    ]
    for name, bucket in sorted(audit['per_check'].items()):
        lines.append(f"- {name}: pass {bucket['pass']} / fail {bucket['fail']} / skip {bucket['skip']}")
    lines += [
        f"- verified 但某项跳过：{audit['verified_with_skipped_check']}",
        f"- verified 却没有任何检查通过：{audit['verified_without_any_pass']}",
        '', '## 类型分布', '', f'- {dict(kinds)}', '',
        '## 失败与重试', '',
    ]
    for record in records:
        if not record.get('ok'):
            lines.append(f"- [{record['n']}] {record['title'][:50]}：{record.get('error', '')[:120]}")
    recovered = [r for r in records if r.get('recovered')]
    lines.append(f'- 触发重排恢复：{len(recovered)} 篇；模型调用合计 {sum(r.get("model_calls") or 0 for r in records)} 次')
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Analyse a v7 shadow run')
    parser.add_argument('run_dir')
    args = parser.parse_args(argv)
    data = analyse(args.run_dir)
    text = render(args.run_dir, data)
    (Path(args.run_dir) / 'analysis.md').write_text(text, encoding='utf-8')
    print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
