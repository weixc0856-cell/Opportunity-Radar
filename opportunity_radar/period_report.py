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

from .intelligence_lines import INTELLIGENCE_LINE_LABEL, INTELLIGENCE_LINES

PERIODS = ('weekly', 'monthly', 'yearly')
LABEL = {'weekly': '周报', 'monthly': '月报', 'yearly': '年报'}
DEFAULT_ECONOMIC_DB = Path('data/economic/economic.sqlite3')

# Source-angle buckets for a personal intelligence station: official record, independent
# media, and market/capital reaction. Derived only from registered source governance fields.
OFFICIAL_TYPES = {'government', 'official_blog', 'industry_association', 'research_organization'}
MEDIA_TYPES = {'news_media', 'independent_expert'}
REGRESSION_LABEL = {'confirmed': '已确认', 'contradicted': '被反证',
                    'open': '仍开放', 'insufficient': '数据不足'}


def _connect(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _window(period, end=None):
    """Reference-period windows, as statistical agencies publish them.

    Weekly is a trailing 7 days. Monthly covers the *previous calendar month* and yearly the
    *previous calendar year*, both half-open [start, end): a report produced at the start of
    month M summarises month M-1, and one produced at the start of year Y summarises year Y-1.
    """
    end_dt = end or datetime.now(timezone.utc)
    if isinstance(end_dt, str):
        end_dt = datetime.fromisoformat(end_dt.replace('Z', '+00:00'))
    if period == 'weekly':
        return end_dt - timedelta(days=7), end_dt
    if period == 'monthly':
        first_this = end_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start_dt = (first_this - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start_dt, first_this
    first_this = end_dt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return first_this.replace(year=first_this.year - 1), first_this


def _iso(value):
    return value.isoformat()


def build(db_path, period='weekly', end=None, economic_db=DEFAULT_ECONOMIC_DB, sources=None):
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
                 AND COALESCE(e.first_seen_at,e.last_seen_at)<?
               GROUP BY e.event_id ORDER BY articles DESC, e.last_seen_at DESC''',
            (start_s, end_s))]
        new_events = sum(1 for event in events if (event['first_seen_at'] or '') >= start_s)
        # Use the article's publication time, not the backfill timestamp: a historical
        # backfill must not make old claims look like this week's news.
        claims = [dict(row) for row in conn.execute(
            '''SELECT c.claim_id, c.event_id, c.article_key, c.subject, c.predicate,
                      c.value_num, c.value_text, c.unit, c.period, c.verification_state,
                      c.extractor, c.rules_version, c.created_at
               FROM claims c LEFT JOIN articles a USING(article_key)
               WHERE COALESCE(a.published,c.created_at)>=?
                 AND COALESCE(a.published,c.created_at)<?
               ORDER BY COALESCE(a.published,c.created_at) DESC''', (start_s, end_s))]
        evidences = [dict(row) for row in conn.execute(
            '''SELECT v.evidence_id, v.article_key, v.source_id, v.source_family,
                      v.independence, v.evidence_kind, v.rules_version, v.created_at
               FROM evidences v LEFT JOIN articles a USING(article_key)
               WHERE COALESCE(a.published,v.created_at)>=?
                 AND COALESCE(a.published,v.created_at)<?''', (start_s, end_s))]
        conflicts = conn.execute(
            'SELECT COUNT(*) FROM claim_conflicts WHERE created_at>=? AND created_at<?',
            (start_s, end_s)).fetchone()[0]
        opportunities = [dict(row) for row in conn.execute(
            '''SELECT opportunity_id, title, problem_statement, buyer_scope,
                      validation_state, confidence, first_seen_at, last_seen_at
               FROM opportunities WHERE first_seen_at>=? AND first_seen_at<?
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
        source_map = _source_map(sources)
        article_source = {r['article_key']: r['source_id'] for r in
                          conn.execute('SELECT article_key, source_id FROM articles')} \
            if _table(conn, 'articles') else {}
        regression = _regression(conn, start_s, end_s, source_map, article_source)
        by_line, by_angle = _aggregates(conn, claims, evidences, source_map, article_source)
        gaps = _gaps(conn, claims, start_s, end_s)
        versions = sorted({c['rules_version'] for c in claims if c.get('rules_version')} |
                          {e.get('rules_version') for e in evidences if e.get('rules_version')})
        rc = regression['counts']
        governing = (f"本期回归：已确认 {rc['confirmed']} · 被反证 {rc['contradicted']} · "
                     f"仍开放 {rc['open']} · 数据不足 {rc['insufficient']}（基线 {regression['baseline_count']} 条主张）。")
        if gaps['claims_without_evidence'] or gaps['analysis_failures']:
            governing += (f" 缺口：无证据主张 {gaps['claims_without_evidence']} · "
                          f"分析失败 {gaps['analysis_failures']}，不作已核实结论。")
        return {
            'period': period, 'label': LABEL[period],
            'window': {'start': start_s, 'end': end_s},
            'events': events, 'event_count': len(events), 'new_events': new_events,
            'multi_article_events': sum(1 for event in events if event['articles'] > 1),
            'claims': claims, 'claim_count': len(claims), 'claim_states': states,
            'evidences': len(evidences), 'source_families': families,
            'conflicts': conflicts, 'opportunities': opportunities,
            'economic': economic[:50],
            'governing': governing, 'regression': regression,
            'by_line': by_line, 'by_angle': by_angle, 'gaps': gaps, 'versions': versions,
            'denominator': f"口径：本窗口进入统计的主张 {len(claims)} 条；无证据与失败单列，不计入已核实。",
            'not_measured': [key for key, value in (
                ('event_clustering_precision_recall', None),
                ('readership_engagement', None)) if value is None],
        }
    finally:
        conn.close()


def _table(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (name,)).fetchone() is not None


def _source_map(sources):
    """source_id -> governance fields. Injected for tests; otherwise read the register.

    Reading the register is reporting-only: it never enables a source or changes scoring.
    """
    if sources is not None:
        out = {}
        for s in sources:
            get = s.get if isinstance(s, dict) else lambda k, d='': getattr(s, k, d)
            out[get('source_id')] = {'source_type': get('source_type') or '',
                                     'provenance_class': get('provenance_class') or '',
                                     'intelligence_lines': get('intelligence_lines') or ''}
        return out
    from . import source_policy
    out = {}
    for path in ('config/sources.csv', 'config/sources.local.csv'):
        try:
            for s in source_policy.load_sources(path):
                out[s.source_id] = {'source_type': s.source_type,
                                    'provenance_class': s.provenance_class,
                                    'intelligence_lines': s.intelligence_lines}
        except (OSError, ValueError):
            continue
    return out


def _angle_of(meta):
    st = str(meta.get('source_type') or ''); pc = str(meta.get('provenance_class') or '')
    lines = str(meta.get('intelligence_lines') or '')
    if st == 'investor_relations' or 'corporate_capital' in lines:
        return '市场/资本'
    if st in OFFICIAL_TYPES or pc == 'official_primary':
        return '官方'
    if st in MEDIA_TYPES or pc in {'professional_media', 'secondhand_report'}:
        return '媒体'
    return '其他/研究'


def _lines_of(meta):
    raw = str(meta.get('intelligence_lines') or '').lower()
    found = [line for line in INTELLIGENCE_LINES if line in raw]
    return found or ['(undeclared)']


def _loc(raw):
    try:
        loc = json.loads(raw or '{}')
    except ValueError:
        return ''
    if not isinstance(loc, dict):
        return ''
    if loc.get('field'):
        start, length = loc.get('start'), loc.get('length')
        if isinstance(start, int) and isinstance(length, int):
            return f"{loc['field']}@{start}-{start + length}"
        return str(loc['field'])
    for key in ('accn', 'series_id', 'period'):
        if loc.get(key):
            return f"{key}={loc[key]}"
    return ''


def _num_diff(a, b):
    """Materially different numeric restatements count as a revision, not confirmation."""
    if a is None or b is None:
        return False
    return abs(a - b) > max(1e-9, 0.01 * abs(a))


def _regression(conn, start_s, end_s, source_map, article_source):
    """Re-test prior claims against this window's new verifications/evidence/conflicts.

    Deterministic: it only reads stored verification_state, claim_verifications,
    claim_conflicts and claim_evidence. It never invents a model judgment.
    """
    baseline = [dict(r) for r in conn.execute(
        "SELECT claim_id, subject, predicate, value_num, unit, period, verification_state, "
        "locator_json, article_key FROM claims WHERE created_at<? AND subject<>'' "
        "ORDER BY created_at", (start_s,))] if _table(conn, 'claims') else []
    counts = {k: 0 for k in REGRESSION_LABEL}
    rows = []
    for claim in baseline:
        cid = claim['claim_id']
        verifs = [dict(r) for r in conn.execute(
            'SELECT verification_id, state, support, created_at FROM claim_verifications '
            'WHERE claim_id=? AND created_at>=? AND created_at<? ORDER BY created_at DESC',
            (cid, start_s, end_s))] if _table(conn, 'claim_verifications') else []
        conflicts = [dict(r) for r in conn.execute(
            'SELECT conflict_id, reason, created_at FROM claim_conflicts '
            'WHERE (claim_a=? OR claim_b=?) AND created_at>=? AND created_at<?',
            (cid, cid, start_s, end_s))] if _table(conn, 'claim_conflicts') else []
        links = [dict(r) for r in conn.execute(
            'SELECT ce.evidence_id, ce.independence, ce.locator_json, v.source_family '
            'FROM claim_evidence ce LEFT JOIN evidences v USING(evidence_id) '
            'WHERE ce.claim_id=? AND ce.created_at>=? AND ce.created_at<?',
            (cid, start_s, end_s))] if _table(conn, 'claim_evidence') else []
        restated = [dict(r) for r in conn.execute(
            'SELECT claim_id, value_num, verification_state, article_key FROM claims '
            'WHERE subject=? AND predicate=? AND claim_id<>? AND created_at>=? AND created_at<?',
            (claim['subject'], claim['predicate'], cid, start_s, end_s))]
        families = {r['source_family'] for r in conn.execute(
            'SELECT v.source_family FROM claim_evidence ce JOIN evidences v USING(evidence_id) '
            'WHERE ce.claim_id=?', (cid,)) if r['source_family']}
        basis = []
        revised = any(_num_diff(claim['value_num'], r['value_num']) for r in restated)
        rejected = any(v['state'] == 'rejected' for v in verifs)
        confirmed_v = any(v['state'] == 'verified' and v['support'] == 'supported' for v in verifs)
        independent_new = len(families) >= 2 and bool(links)
        if conflicts or rejected or revised:
            klass = 'contradicted'
            basis += [f"冲突 {c['conflict_id']}" for c in conflicts[:2]]
            basis += [f"核验 {v['verification_id']}={v['state']}" for v in verifs if v['state'] == 'rejected'][:1]
            basis += [f"修订 {r['claim_id']}" for r in restated if _num_diff(claim['value_num'], r['value_num'])][:1]
        elif confirmed_v or (claim['verification_state'] == 'verified' and independent_new):
            klass = 'confirmed'
            basis += [f"核验 {v['verification_id']}={v['state']}/{v['support']}"
                      for v in verifs if v['state'] == 'verified'][:1]
            basis += [f"证据 {l['evidence_id']}（{l['source_family']}）" for l in links[:2]]
        elif verifs or links or restated:
            klass = 'open'
            basis += [f"核验 {v['verification_id']}={v['state']}" for v in verifs[:1]]
            basis += [f"证据 {l['evidence_id']}" for l in links[:1]]
            basis += [f"重述 {r['claim_id']}" for r in restated[:1]]
        else:
            klass = 'insufficient'
        if not basis:
            loc = _loc(claim['locator_json'])
            basis = [f"原定位 {loc}" if loc else '本窗口无新证据/核验/冲突']
        counts[klass] += 1
        meta = source_map.get(article_source.get(claim['article_key'], ''), {})
        rows.append({'claim_id': cid, 'subject': claim['subject'], 'predicate': claim['predicate'],
                     'line': _lines_of(meta)[0], 'classification': klass,
                     'families': len(families), 'basis': basis[:3]})
    return {'baseline_count': len(baseline), 'counts': counts, 'rows': rows}


def _aggregates(conn, claims, evidences, source_map, article_source):
    """Counts and located-coverage per intelligence line and per source angle."""
    by_line, by_angle = {}, {}

    def bucket(store, key):
        return store.setdefault(key, {'claims': 0, 'evidences': 0, 'located': 0, 'unverified': 0})

    linked = {r['claim_id'] for r in conn.execute('SELECT claim_id FROM claim_evidence')} \
        if _table(conn, 'claim_evidence') else set()
    for claim in claims:
        meta = source_map.get(article_source.get(claim['article_key'], ''), {})
        located = claim['claim_id'] in linked
        for line in _lines_of(meta):
            b = bucket(by_line, line)
            b['claims'] += 1
            b['located'] += 1 if located else 0
            b['unverified'] += 1 if claim['verification_state'] == 'unverified' else 0
        a = bucket(by_angle, _angle_of(meta))
        a['claims'] += 1
        a['located'] += 1 if located else 0
    for evidence in evidences:
        meta = source_map.get(evidence['source_id'], {})
        for line in _lines_of(meta):
            bucket(by_line, line)['evidences'] += 1
        bucket(by_angle, _angle_of(meta))['evidences'] += 1
    line_rows = [{'line': k, 'label': INTELLIGENCE_LINE_LABEL.get(k, k), **v}
                 for k, v in sorted(by_line.items())]
    angle_rows = [{'angle': k, **v} for k, v in sorted(by_angle.items())]
    return line_rows, angle_rows


def _gaps(conn, claims, start_s, end_s):
    linked = {r['claim_id'] for r in conn.execute('SELECT claim_id FROM claim_evidence')} \
        if _table(conn, 'claim_evidence') else set()
    failures = conn.execute('SELECT COUNT(*) FROM analysis_failures WHERE created_at>=? AND created_at<?',
                            (start_s, end_s)).fetchone()[0] if _table(conn, 'analysis_failures') else 0
    run = conn.execute('SELECT coverage, publication_status FROM runs ORDER BY run_id DESC LIMIT 1').fetchone() \
        if _table(conn, 'runs') else None
    return {'claims_without_evidence': sum(1 for c in claims if c['claim_id'] not in linked),
            'unverified': sum(1 for c in claims if c['verification_state'] == 'unverified'),
            'analysis_failures': failures,
            'coverage': run['coverage'] if run else None,
            'publication_status': run['publication_status'] if run else None}


def render_text(report):
    lines = [f"Opportunity Radar · {report['label']}",
             f"窗口：{report['window']['start'][:10]} → {report['window']['end'][:10]}", '']
    if report.get('governing'):
        lines.append(report['governing'])
        lines.append('')
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
    regression = report.get('regression') or {}
    reg_heading = {'monthly': '## 月度回归核验', 'yearly': '## 年度回归核验'}.get(
        report['period'], '## 回归核验')
    lines.append(reg_heading)
    if report['period'] == 'yearly':
        lines.append('口径：自然年窗口（上一年 1 月 1 日—12 月 31 日），次年初总结上一年；'
                     '对全年主张做回归核验，确认/反证/仍开放/数据不足，修订与重述单独标出。')
    elif report['period'] == 'monthly':
        lines.append('口径：自然月窗口（上一自然月），下月初总结上个月；'
                     '对上月主张做回归核验，确认/反证/仍开放/数据不足，修订与重述单独标出。')
    counts = regression.get('counts') or {}
    lines.append('基线主张 %d · %s' % (regression.get('baseline_count', 0), '，'.join(
        f'{REGRESSION_LABEL[k]} {counts.get(k, 0)}' for k in REGRESSION_LABEL)))
    if not regression.get('rows'):
        lines.append('没有可回归的历史主张（基线为空）。')
    for row in regression.get('rows', [])[:30]:
        lines.append(f"- [{REGRESSION_LABEL[row['classification']]}] {row['subject']} · {row['predicate']}"
                     f" · 来源族 {row['families']} · 依据：{'；'.join(row['basis'])}")
    lines.append('')
    lines.append('## 情报主线与来源角度')
    for row in report.get('by_line', []):
        lines.append(f"- {row['label']}：主张 {row['claims']}（有证据 {row['located']}，"
                     f"未核实 {row['unverified']}）· 证据 {row['evidences']}")
    for row in report.get('by_angle', []):
        lines.append(f"- 角度 {row['angle']}：主张 {row['claims']}（有证据 {row['located']}）· 证据 {row['evidences']}")
    if report.get('denominator'):
        lines.append(report['denominator'])
    lines.append('')
    lines.append('## 缺口与版本')
    gaps = report.get('gaps') or {}
    lines.append(f"无证据主张 {gaps.get('claims_without_evidence', 0)} · 未核实 {gaps.get('unverified', 0)} · "
                 f"分析失败 {gaps.get('analysis_failures', 0)} · 覆盖率 {gaps.get('coverage')} · "
                 f"发布门禁 {gaps.get('publication_status')}")
    lines.append('规则版本：' + ('，'.join(report.get('versions') or []) or '未记录'))
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
    regression = report.get('regression') or {}
    regression_rows = ''.join(
        '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
        % (html.escape(REGRESSION_LABEL[row['classification']]),
           html.escape(str(row['subject']) + ' · ' + str(row['predicate'])),
           row['families'], html.escape('；'.join(row['basis'])))
        for row in regression.get('rows', [])[:50])
    line_rows = ''.join(
        '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
        % (html.escape(row['label']), row['claims'], row['located'], row['unverified'], row['evidences'])
        for row in report.get('by_line', []))
    angle_rows = ''.join(
        '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
        % (html.escape(row['angle']), row['claims'], row['located'], row['evidences'])
        for row in report.get('by_angle', []))
    gaps = report.get('gaps') or {}
    template = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>Opportunity Radar __LABEL__</title>
<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#1b1b1b}
table{border-collapse:collapse;width:100%;margin:1rem 0}td,th{border-bottom:1px solid #ddd;padding:.35rem;text-align:left}
h1,h2{font-weight:600}.muted{color:#666}</style></head><body>
<h1>Opportunity Radar · __LABEL__</h1>
<p class="muted">窗口 __START__ → __END__</p>
<p><strong>__GOVERNING__</strong></p>
<p>事件 __EVENT_COUNT__（新增 __NEW_EVENTS__，多文章 __MULTI__） · 主张 __CLAIMS__ · 证据 __EVIDENCES__ · 冲突 __CONFLICTS__</p>
<h2>__REG_HEADING__</h2><table><thead><tr><th>结论</th><th>主张</th><th>来源族</th><th>依据</th></tr></thead><tbody>__REGRESSION__</tbody></table>
<h2>情报主线</h2><table><thead><tr><th>主线</th><th>主张</th><th>有证据</th><th>未核实</th><th>证据</th></tr></thead><tbody>__LINES__</tbody></table>
<h2>来源角度</h2><table><thead><tr><th>角度</th><th>主张</th><th>有证据</th><th>证据</th></tr></thead><tbody>__ANGLES__</tbody></table>
<p class="muted">__DENOMINATOR__</p>
<h2>来源族</h2>__CHART__
<h2>事件</h2><table><thead><tr><th>事件</th><th>文章</th><th>首次</th></tr></thead><tbody>__EVENTS__</tbody></table>
<h2>机会</h2><table><thead><tr><th>状态</th><th>标题</th><th>置信度</th></tr></thead><tbody>__OPPORTUNITIES__</tbody></table>
<h2>经济数据</h2><table><thead><tr><th>数据集</th><th>期间</th><th>公式</th><th>值</th></tr></thead><tbody>__ECONOMIC__</tbody></table>
<p class="muted">缺口：无证据主张 __GAP_NOEV__ · 未核实 __GAP_UNVER__ · 分析失败 __GAP_FAIL__ · 覆盖率 __GAP_COV__ · 门禁 __GAP_GATE__</p>
<p class="muted">规则版本：__VERSIONS__</p>
<p class="muted">未测量：__NOT_MEASURED__</p>
</body></html>"""
    replacements = {
        '__LABEL__': html.escape(report['label']),
        '__START__': html.escape(report['window']['start'][:10]),
        '__END__': html.escape(report['window']['end'][:10]),
        '__GOVERNING__': html.escape(report.get('governing') or ''),
        '__REG_HEADING__': {'monthly': '月度回归核验', 'yearly': '年度回归核验'}.get(
            report['period'], '回归核验'),
        '__REGRESSION__': regression_rows or '<tr><td colspan="4">没有可回归的历史主张。</td></tr>',
        '__LINES__': line_rows or '<tr><td colspan="5">本窗口没有主线记录。</td></tr>',
        '__ANGLES__': angle_rows or '<tr><td colspan="4">本窗口没有角度记录。</td></tr>',
        '__DENOMINATOR__': html.escape(report.get('denominator') or ''),
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
        '__GAP_NOEV__': str(gaps.get('claims_without_evidence', 0)),
        '__GAP_UNVER__': str(gaps.get('unverified', 0)),
        '__GAP_FAIL__': str(gaps.get('analysis_failures', 0)),
        '__GAP_COV__': html.escape(str(gaps.get('coverage'))),
        '__GAP_GATE__': html.escape(str(gaps.get('publication_status'))),
        '__VERSIONS__': html.escape('，'.join(report.get('versions') or []) or '未记录'),
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
