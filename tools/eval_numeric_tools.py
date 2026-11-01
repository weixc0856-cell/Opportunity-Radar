"""Compare the built-in N1 rules with Microsoft Recognizers-Text on the spec's expressions.

This is an evaluation harness, not part of the runtime. It imports Recognizers-Text only if
it is installed in the interpreter that runs the script; the project runtime never imports
it. Run it with an interpreter that has the recognizers packages:

    python tools/eval_numeric_tools.py
    <venv>/Scripts/python.exe tools/eval_numeric_tools.py --out data/claim-pipeline/tool-eval

It reports, per method: candidates found, correctly located (raw text equals the text slice),
unclassified, duplicate (overlapping) matches, misrecognitions, and digit coverage. It does
not treat a recognizer's resolution as a claim value.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from opportunity_radar import article_text, numeric_candidates  # noqa: E402

# The expressions the batch spec requires, plus the BEA sentences the model was missing.
SAMPLES = [
    '0.2%', '0.2 percent', '2 percentage points', '$92.8bn', 'USD 12.8 billion',
    '5 million vehicles', '1.5', '2.1–2.5%',
    'increased 0.2%', 'declined by 0.5 percent', 'rose from 3.2% to 3.8%',
    'fell to $92.8bn from $95bn', 'up 2 percentage points',
    'September 2026', 'Q3 2026', 'FY2025', 'year over year', 'month-on-month',
    'over the past 12 months',
    '1,234,567', '-0.5%', '(0.5%)', '0.002', '1.2e-5', '15 per 100', '3:1',
    'Article 5', 'call +1-800-555-1234', 'see [12]', '10-K', 'Form 8-K', 'v2.0',
    'Personal income increased $54.5 billion (0.2 percent at a monthly rate) in September.',
    'The deficit increased from $92.8 billion in July (revised) to $105.6 billion in August.',
    'The goods deficit increased $12.8 billion in August to $136.6 billion.',
    'The services surplus increased less than $0.1 billion in August to $31.0 billion.',
]


def _versions():
    import importlib.metadata as metadata
    out = {'python': platform.python_version()}
    for package in ('recognizers-text', 'recognizers-text-number',
                    'recognizers-text-number-with-unit', 'emoji'):
        try:
            out[package] = metadata.version(package)
        except Exception:
            out[package] = 'missing'
    return out


def _recognizers_available():
    try:
        import recognizers_number  # noqa: F401
        import recognizers_number_with_unit  # noqa: F401
        return True
    except Exception:
        return False


def _recognizer_entities(text):
    """Accepted recognizer entities with half-open offsets, or None when unavailable."""
    from recognizers_text import Culture
    from recognizers_number import recognize_number
    from recognizers_number_with_unit import recognize_currency, recognize_dimension

    raw = []
    for method, function, candidate_type in (
            ('number', recognize_number, 'scalar'),
            ('currency', recognize_currency, 'currency'),
            ('dimension', recognize_dimension, 'quantity')):
        try:
            results = function(text, Culture.English)
        except Exception as exc:  # one broken recognizer must not hide the others
            raw.append({'method': method, 'error': f'{type(exc).__name__}: {exc}'})
            continue
        for item in results:
            # Recognizers-Text reports the index of the last character (inclusive).
            start, end = int(item.start), int(item.end) + 1
            raw.append({'method': method, 'candidate_type': candidate_type,
                        'start': start, 'end': end, 'raw_text': text[start:end],
                        'entity_text': getattr(item, 'text', ''),
                        'resolution': getattr(item, 'resolution', None)})
    entities = [item for item in raw if 'error' not in item]
    entities.sort(key=lambda item: (item['start'], -(item['end'] - item['start'])))
    accepted, duplicates, last_end = [], 0, -1
    for entity in entities:
        if entity['start'] < last_end:
            duplicates += 1
            continue
        accepted.append(entity)
        last_end = entity['end']
    return accepted, duplicates, [item for item in raw if 'error' in item]


def _rule_entities(result):
    return [{'candidate_type': candidate['candidate_type'],
             'start': candidate['start'], 'end': candidate['end'],
             'raw_text': candidate['raw_text'],
             'detection_status': candidate['detection_status']}
            for candidate in result['candidates']]


def _metrics(entities, text):
    located = sum(1 for entity in entities if entity['raw_text'] == text[entity['start']:entity['end']])
    unclassified = sum(1 for entity in entities
                       if entity.get('candidate_type') == 'unclassified_numeric')
    digits = {index for index, char in enumerate(text) if char.isdecimal()}
    covered = set()
    for entity in entities:
        covered.update(index for index in range(entity['start'], entity['end'])
                       if index in digits)
    return {'candidates': len(entities), 'located': located,
            'unclassified': unclassified,
            'misrecognitions': len(entities) - located,
            'digit_coverage': f'{len(covered)}/{len(digits)}',
            'digit_coverage_complete': covered == digits}


def _dedupe(rule_entities, recognizer_entities):
    combined = list(rule_entities)
    spans = [(item['start'], item['end']) for item in combined]
    added = 0
    for entity in recognizer_entities:
        if any(entity['start'] < end and start < entity['end'] for start, end in spans):
            continue
        combined.append(dict(entity, detection_method='recognizers_text'))
        spans.append((entity['start'], entity['end']))
        added += 1
    combined.sort(key=lambda item: item['start'])
    return combined, added


def evaluate():
    available = _recognizers_available()
    rows, totals = [], {}
    for sample in SAMPLES:
        document = article_text.build({'title': '', 'content': sample,
                                       'content_format': 'text'})
        text = document.field('body').text
        result = numeric_candidates.extract(document)
        rules = _rule_entities(result)
        recognizers, duplicates, errors = ([], 0, [])
        if available:
            recognizers, duplicates, errors = _recognizer_entities(text)
        combined, added = _dedupe(rules, recognizers) if available else (rules, 0)
        row = {
            'sample': sample,
            'text': text,
            'rules': rules,
            'recognizers_text': recognizers,
            'recognizer_duplicates': duplicates,
            'recognizer_errors': errors,
            'combined': combined,
            'combined_added': added,
            'metrics': {'rules': _metrics(rules, text)},
        }
        if available:
            row['metrics']['recognizers_text'] = _metrics(recognizers, text)
            row['metrics']['combined'] = _metrics(combined, text)
        rows.append(row)
        for method, entities in (('rules', rules), ('recognizers_text', recognizers),
                                 ('combined', combined)):
            if not available and method != 'rules':
                continue
            bucket = totals.setdefault(method, {'candidates': 0, 'located': 0,
                                                'unclassified': 0, 'misrecognitions': 0,
                                                'coverage_complete_samples': 0})
            metric = _metrics(entities, text)
            bucket['coverage_complete_samples'] += 1 if metric['digit_coverage_complete'] else 0
            bucket['candidates'] += metric['candidates']
            bucket['located'] += metric['located']
            bucket['unclassified'] += metric['unclassified']
            bucket['misrecognitions'] += metric['misrecognitions']
        totals.setdefault('recognizer_duplicates', 0)
        totals['recognizer_duplicates'] += duplicates
    return {'available': available, 'versions': _versions(), 'totals': totals, 'samples': rows}


def render(report):
    lines = ['# N1 识别器对比（规则 / Recognizers-Text / 组合）', '',
             f"- Python：{report['versions']['python']}",
             f"- Recognizers-Text 可用：{'是' if report['available'] else '否'}"]
    for package, version in report['versions'].items():
        if package != 'python':
            lines.append(f"- {package}：{version}")
    lines += ['', '## 汇总', '',
              '| 方法 | 候选 | 正确定位 | 未分类 | 定位失败 | 数字覆盖完整样本 |', '|---|---|---|---|---|---|']
    for method, bucket in report['totals'].items():
        if method == 'recognizer_duplicates':
            continue
        lines.append(f"| {method} | {bucket['candidates']} | {bucket['located']} | "
                     f"{bucket['unclassified']} | {bucket['misrecognitions']} | "
                     f"{bucket['coverage_complete_samples']}/{len(report['samples'])} |")
    lines.append(f"| 识别器重复/重叠 | {report['totals'].get('recognizer_duplicates', 0)} | — | — | — |")
    lines += ['', '## 逐例', '',
              '| 输入 | 规则发现 | Recognizers-Text | 组合新增 |', '|---|---|---|---|']
    for row in report['samples']:
        rules = '、'.join(f"{item['candidate_type']}:{item['raw_text']}" for item in row['rules']) or '—'
        if report['available']:
            rec = '、'.join(f"{item['candidate_type']}:{item['raw_text']}" for item in row['recognizers_text']) or '—'
        else:
            rec = '未安装'
        lines.append(f"| `{row['sample'][:40]}` | {rules} | {rec} | {row['combined_added']} |")
    if not report['available']:
        lines += ['', '识别器未安装：以上只记录规则结果；安装说明见验收记录。']
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Compare N1 rules with Recognizers-Text')
    parser.add_argument('--out', default=str(ROOT / 'data' / 'claim-pipeline' / 'tool-eval'))
    args = parser.parse_args(argv)
    report = evaluate()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'comparison.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'comparison.md').write_text(render(report), encoding='utf-8')
    print(render(report))
    print(f'written to {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
