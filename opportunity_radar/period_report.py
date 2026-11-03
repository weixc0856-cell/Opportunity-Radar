"""R4 weekly and monthly reports rebuilt from the event/evidence/claim graph.

These reports are not a concatenation of daily briefs. They read the stored events,
evidences, claims, opportunities and economic observations for a date window and render
what changed, what is corroborated, and what remains unverified.
"""
from __future__ import annotations

import html
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

PERIODS = ('weekly', 'monthly')
LABEL = {'weekly': '周报', 'monthly': '月报'}
DEFAULT_ECONOMIC_DB = Path('data/economic/economic.sqlite3')


def _connect(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _window(period, end=None):
    end_dt = end or datetime.now(timezone.utc)
    if isinstance(end_dt, str):
        end_dt = datetime.fromisoformat(end_dt.replace('Z', '+00:00'))
    days = 7 if period == 'weekly' else 30
    start_dt = end_dt - timedelta(days=days)
    return start_dt, end_dt


def _iso(value):
    return value.isoformat()


def build(db_path, period='weekly', end=None, economic_db=DEFAULT_ECONOMIC_DB):
    if period not in PERIODS:
        raise ValueError(f'unknown period: {period!r}')
    start, end = _window(period, end)
    start_s, end_s = _iso(start), _iso(end)
    conn = _connect(db_path)
    try:
        events = [dict(row) for row in conn.execute(
            '''SELECT e.event_id, e.title_norm, e.event_type, e.first_seen_at, e.last_seen_at,
                      COUNT(ea.article_key) AS articles
               FROM events e LEFT JOIN event_articles ea USING(event_id)
               WHERE COALESCE(e.last_seen_at,e.first_seen_at)>=?
                 AND COALESCE(e.first_seen_at,e.last_seen_at)<=?
               GROUP BY e.event_id ORDER BY articles DESC, e.last_seen_at DESC''',
            (start_s, end_s))]
        new_events = sum(1 for event in events if (event['first_seen_at'] or '') >= start_s)
        # Use the article's publication time, not the backfill timestamp: a historical
        # backfill must not make old claims look like this week's news.
        claims = [dict(row) for row in conn.execute(
            '''SELECT c.claim_id, c.event_id, c.article_key, c.subject, c.predicate,
                      c.value_num, c.value_text, c.unit, c.period, c.verification_state,
                      c.extractor, c.created_at
               FROM claims c LEFT JOIN articles a USING(article_key)
               WHERE COALESCE(a.published,c.created_at)>=?
                 AND COALESCE(a.published,c.created_at)<=?
               ORDER BY COALESCE(a.published,c.created_at) DESC''', (start_s, end_s))]
        evidences = [dict(row) for row in conn.execute(
            '''SELECT v.evidence_id, v.article_key, v.source_id, v.source_family,
                      v.independence, v.evidence_kind, v.created_at
               FROM evidences v LEFT JOIN articles a USING(article_key)
               WHERE COALESCE(a.published,v.created_at)>=?
                 AND COALESCE(a.published,v.created_at)<=?''', (start_s, end_s))]
        conflicts = conn.execute(
            'SELECT COUNT(*) FROM claim_conflicts WHERE created_at>=? AND created_at<=?',
            (start_s, end_s)).fetchone()[0]
        opportunities = [dict(row) for row in conn.execute(
            '''SELECT opportunity_id, title, problem_statement, buyer_scope,
                      validation_state, confidence, first_seen_at, last_seen_at
               FROM opportunities WHERE first_seen_at>=? AND first_seen_at<=?
               ORDER BY first_seen_at DESC''', (start_s, end_s))] \
            if _table(conn, 'opportunities') else []
        economic = []
        if Path(economic_db).exists():
            econ = _connect(economic_db)
            try:
                economic = [dict(row) for row in econ.execute(
                    '''SELECT d.dataset_id, d.provider, d.indicator, m.period, m.formula, m.value
                       FROM derived_metrics m JOIN datasets d USING(dataset_id)
                       ORDER BY m.period DESC, d.dataset_id LIMIT 50''')]
            finally:
                econ.close()
        states = {}
        for claim in claims:
            states[claim['verification_state']] = states.get(claim['verification_state'], 0) + 1
        families = {}
        for evidence in evidences:
            family = evidence['source_family'] or evidence['source_id'] or 'unknown'
            families[family] = families.get(family, 0) + 1
        return {
            'period': period, 'label': LABEL[period],
            'window': {'start': start_s, 'end': end_s},
            'events': events, 'event_count': len(events), 'new_events': new_events,
            'multi_article_events': sum(1 for event in events if event['articles'] > 1),
            'claims': claims, 'claim_count': len(claims), 'claim_states': states,
            'evidences': len(evidences), 'source_families': families,
            'conflicts': conflicts, 'opportunities': opportunities,
            'economic': economic[:50],
            'not_measured': [key for key, value in (
                ('event_clustering_precision_recall', None),
                ('readership_engagement', None)) if value is None],
        }
    finally:
        conn.close()


def _table(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (name,)).fetchone() is not None


def render_text(report):
    lines = [f"Opportunity Radar · {report['label']}",
             f"窗口：{report['window']['start'][:10]} → {report['window']['end'][:10]}", '']
    lines.append(f"事件：{report['event_count']}（新增 {report['new_events']}，"
                 f"多文章事件 {report['multi_article_events']}）")
    lines.append(f"主张：{report['claim_count']} · 证据：{report['evidences']} · "
                 f"冲突：{report['conflicts']}")
    if report['claim_states']:
        lines.append('主张状态：' + '，'.join(
            f'{key} {value}' for key, value in sorted(report['claim_states'].items())))
    if report['source_families']:
        lines.append('来源族：' + '，'.join(
            f'{key} {value}' for key, value in sorted(
                report['source_families'].items(), key=lambda item: -item[1])))
    lines.append('')
    lines.append('## 事件')
    if not report['events']:
        lines.append('本窗口没有事件记录。')
    for event in report['events'][:30]:
        lines.append(f"- {event['title_norm'] or event['event_id']} · 文章 {event['articles']}"
                     f" · 首次 {str(event['first_seen_at'])[:10]}")
    lines.append('')
    lines.append('## 机会')
    if not report['opportunities']:
        lines.append('本窗口没有新建 Opportunity。')
    for item in report['opportunities'][:30]:
        lines.append(f"- [{item['validation_state']}] {item['title'] or item['opportunity_id']}"
                     f" · 置信度 {item['confidence']:.2f}")
    lines.append('')
    lines.append('## 经济数据')
    if not report['economic']:
        lines.append('本窗口没有新的派生指标。')
    for item in report['economic'][:20]:
        lines.append(f"- {item['dataset_id']} {item['period']} {item['formula']} ="
                     f" {item['value']}")
    lines.append('')
    lines.append('未测量：' + '，'.join(report['not_measured']))
    return '\n'.join(lines) + '\n'



def render_html(report):
    """A minimal, dependency-free HTML edition with an inline source-family chart."""
    families = sorted(report['source_families'].items(), key=lambda item: -item[1])[:10]
    top = max([value for _, value in families] or [1])
    bars = []
    for index, (name, value) in enumerate(families):
        width = max(2, int(240 * value / top))
        y = 8 + index * 26
        bars.append(
            '<text x="0" y="%d" font-size="12">%s</text>'
            '<rect x="150" y="%d" width="%d" height="14" fill="#3b6ea5"/>'
            '<text x="%d" y="%d" font-size="12">%d</text>'
            % (y + 14, html.escape(str(name)), y + 3, width, 155 + width, y + 14, value))
    chart = ('<svg width="460" height="%d" role="img" aria-label="source family counts">%s</svg>'
             % (16 + 26 * max(1, len(families)), ''.join(bars)))
    event_rows = ''.join(
        '<tr><td>%s</td><td>%s</td><td>%s</td></tr>'
        % (html.escape(str(event.get('title_norm') or event.get('event_id'))),
           event.get('articles'), html.escape(str(event.get('first_seen_at') or '')[:10]))
        for event in report['events'][:50])
    opportunity_rows = ''.join(
        '<tr><td>%s</td><td>%s</td><td>%.2f</td></tr>'
        % (html.escape(str(item.get('validation_state'))),
           html.escape(str(item.get('title') or item.get('opportunity_id'))),
           float(item.get('confidence') or 0))
        for item in report['opportunities'][:50])
    economic_rows = ''.join(
        '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
        % (html.escape(str(item.get('dataset_id'))), html.escape(str(item.get('period'))),
           html.escape(str(item.get('formula'))), item.get('value'))
        for item in report['economic'][:30])
    template = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>Opportunity Radar __LABEL__</title>
<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#1b1b1b}
table{border-collapse:collapse;width:100%;margin:1rem 0}td,th{border-bottom:1px solid #ddd;padding:.35rem;text-align:left}
h1,h2{font-weight:600}.muted{color:#666}</style></head><body>
<h1>Opportunity Radar · __LABEL__</h1>
<p class="muted">窗口 __START__ → __END__</p>
<p>事件 __EVENT_COUNT__（新增 __NEW_EVENTS__，多文章 __MULTI__） · 主张 __CLAIMS__ · 证据 __EVIDENCES__ · 冲突 __CONFLICTS__</p>
<h2>来源族</h2>__CHART__
<h2>事件</h2><table><thead><tr><th>事件</th><th>文章</th><th>首次</th></tr></thead><tbody>__EVENTS__</tbody></table>
<h2>机会</h2><table><thead><tr><th>状态</th><th>标题</th><th>置信度</th></tr></thead><tbody>__OPPORTUNITIES__</tbody></table>
<h2>经济数据</h2><table><thead><tr><th>数据集</th><th>期间</th><th>公式</th><th>值</th></tr></thead><tbody>__ECONOMIC__</tbody></table>
<p class="muted">未测量：__NOT_MEASURED__</p>
</body></html>"""
    replacements = {
        '__LABEL__': html.escape(report['label']),
        '__START__': html.escape(report['window']['start'][:10]),
        '__END__': html.escape(report['window']['end'][:10]),
        '__EVENT_COUNT__': str(report['event_count']),
        '__NEW_EVENTS__': str(report['new_events']),
        '__MULTI__': str(report['multi_article_events']),
        '__CLAIMS__': str(report['claim_count']),
        '__EVIDENCES__': str(report['evidences']),
        '__CONFLICTS__': str(report['conflicts']),
        '__CHART__': chart,
        '__EVENTS__': event_rows or '<tr><td colspan="3">本窗口没有事件记录。</td></tr>',
        '__OPPORTUNITIES__': opportunity_rows or '<tr><td colspan="3">本窗口没有新建 Opportunity。</td></tr>',
        '__ECONOMIC__': economic_rows or '<tr><td colspan="4">本窗口没有派生指标。</td></tr>',
        '__NOT_MEASURED__': html.escape('，'.join(report['not_measured'])),
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    return template

def write(report, out_dir='reports', archive=True):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime('%Y-%m-%d-%H%M%S')
    name = f"{report['period']}-{stamp}"
    text = render_text(report)
    html_text = render_html(report)
    (out / f'{name}.txt').write_text(text, encoding='utf-8')
    (out / f'{name}.html').write_text(html_text, encoding='utf-8')
    (out / f'{name}.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    if archive:
        arch = out / 'archive' / datetime.now().astimezone().strftime('%Y/%m/%d')
        arch.mkdir(parents=True, exist_ok=True)
        (arch / f'{name}.txt').write_text(text, encoding='utf-8')
        (arch / f'{name}.html').write_text(html_text, encoding='utf-8')
        (arch / f'{name}.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    return {'text': str(out / f'{name}.txt'), 'html': str(out / f'{name}.html'),
            'json': str(out / f'{name}.json'), 'text_value': text, 'report': report}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Build a weekly or monthly report')
    parser.add_argument('period', choices=PERIODS)
    parser.add_argument('--db', default='data/opportunity_radar.sqlite3')
    parser.add_argument('--out', default='reports')
    parser.add_argument('--end', default='')
    args = parser.parse_args()
    result = write(build(args.db, args.period, args.end or None), args.out)
    print(result['text_value'])
