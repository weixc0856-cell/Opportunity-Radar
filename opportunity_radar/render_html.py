"""HTML edition of the brief.

Design intent: a printed consulting document, not a web page. The page is a fixed
max-width sheet with a cover, a numbering system, restrained typography and a print
stylesheet, so it reads the same on screen and on paper. All text is escaped; the only
links are https URLs from source metadata.
"""
from collections import Counter
from datetime import datetime
from html import escape
from urllib.parse import urlparse

from .analytics import funnel, source_breakdown, evidence_breakdown, denominator_note, lane_breakdown
from .digest import (REASON_LABEL, SOURCE_LABEL, MARKET_LABEL, WEIGHT_LABEL,
                     decision_headline, appendix_note, management_note, empty_reason, _pay_strong, _judgment,
                     _why, _evidence_text, _market, _commercial_line, _lane, _state, _shown, _deferred,
                     STATUS_LABEL, group_by_event, event_summary_lines, event_status_note, _v5_sections,
                     _one_line, _action_title, _evidence_basis, _implication, _confidence,
                     _next_actions, _hypotheses, _risks, _watch_rows, _judgment_pool, _order_key)
from .evidence import STATE_LABEL, STATE_MEANING, EVIDENCE_STATES
from .intelligence_lines import INTELLIGENCE_LINE_LABEL, summarize
from .lanes import LANE_LABEL, LANE_PROMISE
from .publication import disclosure
from . import display

INK = '#111827'; INK2 = '#374151'; MUTED = '#6b7280'; RULE = '#e5e7eb'
ACCENT = '#b45309'; BRAND = '#d9730d'; WASH = '#fbf7f2'; PANEL = '#f9fafb'
FONT = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,"
        "'PingFang SC','Microsoft YaHei',sans-serif")
MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"

STYLE = f"""
:root{{--ink:{INK};--ink2:{INK2};--muted:{MUTED};--rule:{RULE};--accent:{ACCENT};--wash:{WASH};--panel:{PANEL}}}
*{{box-sizing:border-box}}
html{{-webkit-text-size-adjust:100%}}
body{{margin:0;background:#eef0f3;color:var(--ink);font-family:{FONT};
 font-size:14px;line-height:1.7;-webkit-font-smoothing:antialiased}}
a{{color:var(--accent);text-decoration:none;border-bottom:1px solid rgba(180,83,9,.35)}}
.sheet{{max-width:880px;margin:0 auto;background:#fff;padding:0 0 64px}}
.cover{{background:var(--ink);color:#fff;padding:56px 56px 40px;margin-bottom:8px}}
.cover .brand{{font-size:10.5px;letter-spacing:.34em;color:#f0b27a;font-weight:700}}
.cover h1{{margin:16px 0 6px;font-size:38px;line-height:1.15;font-weight:800;letter-spacing:-.02em}}
.cover .sub{{color:#c7ccd4;font-size:13.5px;margin-bottom:34px}}
.cover .rule{{height:3px;background:{BRAND};width:64px;margin:26px 0 22px}}
.meta{{display:grid;grid-template-columns:repeat(4,1fr);gap:18px 24px;margin-top:6px}}
.meta .k{{font-size:9.5px;letter-spacing:.14em;color:#98a0ab;text-transform:uppercase}}
.meta .v{{font-size:13px;color:#fff;margin-top:3px;font-weight:600}}
.kpi{{display:grid;grid-template-columns:repeat(4,1fr);gap:0;background:var(--ink);color:#fff;
 border-top:1px solid #2a303a;padding:22px 56px 26px}}
.kpi .cell{{padding-right:18px;border-right:1px solid #2a303a}}
.kpi .cell:last-child{{border-right:0}}
.kpi .n{{font-size:30px;font-weight:800;line-height:1.05;letter-spacing:-.02em}}
.kpi .l{{font-size:10px;letter-spacing:.12em;color:#98a0ab;text-transform:uppercase;margin-top:6px}}
.wrap{{padding:0 56px}}
section{{margin-top:38px;page-break-inside:auto}}
h2{{display:flex;align-items:baseline;gap:12px;font-size:18px;font-weight:800;letter-spacing:-.01em;
 margin:0 0 14px;padding-bottom:8px;border-bottom:1px solid var(--rule)}}
h2 .num{{font-family:{MONO};font-size:11px;font-weight:700;color:var(--accent);letter-spacing:.08em}}
h2 .en{{margin-left:auto;font-size:10.5px;font-weight:600;color:var(--muted);letter-spacing:.12em;
 text-transform:uppercase}}
.governing{{font-size:21px;line-height:1.5;font-weight:700;margin:0 0 16px;
 border-left:3px solid {BRAND};padding-left:18px}}
.note{{background:var(--wash);border:1px solid #f0e3d3;padding:14px 16px;font-size:13px;
 line-height:1.8;color:#4a3b2a;margin:0}}
.kj{{border-top:1px solid var(--rule)}}
.kj .item{{padding:16px 0;border-bottom:1px solid var(--rule);page-break-inside:avoid}}
.kj .tag{{font-family:{MONO};font-size:10.5px;font-weight:700;color:var(--accent);letter-spacing:.1em}}
.kj h3{{font-size:15.5px;line-height:1.55;margin:5px 0 10px;font-weight:700}}
.kv{{display:grid;grid-template-columns:64px 1fr;gap:4px 14px;font-size:12.5px;line-height:1.65}}
.kv dt{{color:var(--muted);font-weight:600}}
.kv dd{{margin:0;color:var(--ink2)}}
.ol{{list-style:none;margin:0;padding:0;counter-reset:a}}
.ol li{{counter-increment:a;display:grid;grid-template-columns:26px 1fr;gap:10px;
 padding:12px 0;border-bottom:1px solid var(--rule);page-break-inside:avoid}}
.ol li:before{{content:counter(a);font-family:{MONO};font-size:12px;font-weight:700;color:var(--accent)}}
.ol .step{{font-size:13.5px;line-height:1.6}}
.ol .done{{font-size:12px;color:var(--muted);line-height:1.65;margin-top:4px}}
.hy{{background:var(--panel);border:1px solid var(--rule);padding:6px 16px;margin:0}}
.hy .item{{padding:10px 0;border-bottom:1px solid var(--rule)}}
.hy .item:last-child{{border-bottom:0}}
.hy .tag{{font-family:{MONO};font-size:11px;font-weight:700;color:var(--accent)}}
.hy .t{{font-size:13px;line-height:1.65}}
.hy .m{{font-size:11.5px;color:var(--muted);margin-top:3px}}
ul.risk{{margin:0;padding-left:18px}}
ul.risk li{{font-size:13px;color:var(--ink2);line-height:1.75;margin:5px 0}}
table{{width:100%;border-collapse:collapse}}
th{{text-align:left;font-size:9.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);
 font-weight:700;padding:0 10px 8px 0;border-bottom:1px solid var(--rule)}}
td{{font-size:12.5px;line-height:1.6;color:var(--ink2);padding:9px 10px 9px 0;
 border-bottom:1px solid var(--rule);vertical-align:top}}
td.mono{{font-family:{MONO};white-space:nowrap;color:var(--ink)}}
.card{{border:1px solid var(--rule);padding:16px 18px;margin-bottom:14px;page-break-inside:avoid}}
.card h4{{margin:0 0 2px;font-size:14px;line-height:1.55;font-weight:700}}
.card .meta-line{{font-size:11px;color:var(--muted);margin-bottom:10px}}
.card .score{{font-family:{MONO};color:var(--accent);font-weight:700;margin-right:6px}}
.chart{{margin:18px 0 0;page-break-inside:avoid}}
.chart .t{{font-size:10.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);
 font-weight:700;margin-bottom:8px}}
.muted{{color:var(--muted);font-size:12px;line-height:1.7}}
.panel{{background:var(--panel);border:1px solid var(--rule);padding:14px 16px;font-size:12.5px;
 line-height:1.75;color:var(--ink2)}}
.warn{{background:#fff7ed;border:1px solid #fdba74;color:#7c2d12;padding:12px 14px;font-size:12.5px;line-height:1.75}}
.foot{{margin-top:36px;padding-top:14px;border-top:1px solid var(--rule);font-size:11px;color:var(--muted);line-height:1.7}}
@media (max-width:720px){{
 .sheet{{padding-bottom:40px}} .cover{{padding:34px 20px 26px}} .cover h1{{font-size:28px}}
 .meta{{grid-template-columns:repeat(2,1fr)}} .kpi{{grid-template-columns:repeat(2,1fr);gap:16px;padding:18px 20px}}
 .kpi .cell{{border-right:0}} .wrap{{padding:0 20px}} .governing{{font-size:18px}}
 .kv{{grid-template-columns:56px 1fr}}
}}
@media print{{
 @page{{size:A4;margin:14mm}}
 body{{background:#fff;font-size:10.5pt}}
 .sheet{{max-width:none;padding-bottom:0}}
 .cover{{page-break-after:always;margin-bottom:0}}
 .kpi{{padding:16px 0 0;background:#fff;color:var(--ink);border-top:2px solid var(--ink)}}
 .kpi .l{{color:var(--muted)}} .kpi .cell{{border-right:1px solid var(--rule)}}
 .meta .v,.cover h1,.cover .sub{{color:var(--ink)}} .cover{{background:#fff;color:var(--ink);padding:0 0 24px}}
 .cover .brand{{color:var(--accent)}}
 section{{margin-top:22px}} h2{{page-break-after:avoid}} .card,.kj .item,.ol li{{page-break-inside:avoid}}
}}
"""


def _e(value):
    return escape(str(value if value is not None else ''), quote=True)


def _safe_href(value):
    """Only render secure web links from untrusted source metadata."""
    raw = str(value or '').strip()
    try:
        parsed = urlparse(raw)
        if parsed.scheme.lower() != 'https' or not parsed.hostname or parsed.username or parsed.password:
            return ''
        return _e(raw)
    except ValueError:
        return ''


def _section(n, title, en=''):
    return (f'<section><h2><span class="num">{n:02d}</span><span>{_e(title)}</span>'
            + (f'<span class="en">{_e(en)}</span>' if en else '')
            + '</h2>')


def _kv(k, v):
    return f'<dt>{_e(k)}</dt><dd>{v}</dd>'


def _chart_block(title, rows, color_note=''):
    if not rows:
        return ''
    bars = _svg_bars(rows)
    note = f'<div class="muted" style="margin-top:4px;">{_e(color_note)}</div>' if color_note else ''
    return f'<div class="chart"><div class="t">{_e(title)}</div>{bars}{note}</div>'


def _svg_bars(rows):
    """Horizontal bars, sized to the largest value, labelled with their count."""
    rows = [(str(r[0]), int(r[1]), str(r[2]) if len(r) > 2 else '') for r in rows]
    top = max([value for _, value, _ in rows] or [1]) or 1
    height = 26 * len(rows) + 8
    out = [f'<svg role="img" viewBox="0 0 640 {height}" width="100%" height="{height}" '
           f'style="display:block;max-width:640px;">']
    for i, (label, value, note) in enumerate(rows):
        y = 8 + i * 26
        width = max(2.0, 420.0 * value / top)
        out.append(f'<text x="0" y="{y + 13}" font-size="11" fill="{INK2}" font-family="{FONT}">{_e(label[:18])}</text>')
        out.append(f'<rect x="150" y="{y + 3}" width="{width:.1f}" height="14" rx="2" fill="{BRAND}" opacity="0.85"/>')
        suffix = f'  {note}' if note else ''
        out.append(f'<text x="{150 + width + 8:.1f}" y="{y + 14}" font-size="11" fill="{MUTED}" '
                   f'font-family="{MONO}">{value}{_e(suffix)}</text>')
    out.append('</svg>')
    return ''.join(out)


def _quote_rows(ev):
    """Unlocated quotations get their own row and their own label, never 事实."""
    verified = [e for e in ev if e.get('field') != 'unlocated']
    unverified = [e for e in ev if e.get('field') == 'unlocated']
    fmt = lambda e: _e(f"[{e.get('id')}] {e.get('quote', '')}" if e.get('id') else e.get('quote', ''))
    rows = _kv('事实（可在原文定位）', ('；'.join(fmt(e) for e in verified) if verified else '无可定位引文'))
    if unverified:
        rows += _kv('未核实引文', _e('；'.join(fmt(e) for e in unverified)) + '（原文中未找到，不作为事实）')
    return rows


def _estimate_row(x):
    if x.get('content_basis_estimate') == 'full_text' and x.get('evidence_basis') != 'full_text':
        return _kv('内容完整性估计',
                   '这段文本看起来是全文；只有把该来源复核为 content_access_level=full_text，才能按 E2 计。')
    return ''


def _finding(x):
    """Appendix card: everything needed to trace the judgment back to the source."""
    a = x.get('analysis', {}); cls = x.get('classification', {}); lane = _lane(x)
    ev = x.get('evidence') or []
    href = _safe_href(x.get('url', ''))
    link = (f'<a href="{href}" rel="noopener noreferrer">打开原文 ↗</a>' if href else '原文链接不可用')
    rows = (_kv('通道', f'{_e(lane)} · {_e(LANE_LABEL[lane])}')
            + _kv('证据', f'{_e(_evidence_text(x))} · 来源质量 {_e(SOURCE_LABEL.get(cls.get("source_quality"), cls.get("source_quality", "")))}'))
    if a.get('schema_version') == 5:
        body = '<div style="white-space:pre-wrap;font-size:12px;line-height:1.7;">' + \
               '<br>'.join(_e(line.strip()) for line in _v5_sections(x, (x.get('event') or {}).get('evidence_status'))) + '</div>'
        rows += (_kv('事实与推断', body)
                 + _kv('商业评估' if lane != 'C' else '技术评估', _e(_commercial_line(x).strip()))
                 + _kv('来源', f'{_e(x.get("source_name", "Unknown"))} · {link}'))
    else:
        rows += (_kv('初判', _e(_judgment(a)))
                 + _quote_rows(ev) + _estimate_row(x)
                 + _kv('商业评估' if lane != 'C' else '技术评估', _e(_commercial_line(x).strip()))
                 + _kv('关键未知', _e('；'.join(a.get('uncertainties', [])) or '未填写'))
                 + _kv('下一步观察', _e(a.get('suggested_next_step', '人工复核')))
                 + _kv('来源', f'{_e(x.get("source_name", "Unknown"))} · {link}'))
    priority = x.get('editorial_priority', '—')
    return (f'<article class="card">'
            f'<h4><span class="score">{_e(x.get("score", 0))}</span>{_e(x.get("title", ""))}</h4>'
            f'<div class="meta-line">初筛 {_e(x.get("score", 0))}/100 · 优先级 {_e(priority)} · '
            f'信号 {_e(x.get("signal_score", x.get("score", 0)))}/100 · 证据 {_e(x.get("evidence_score", 0))}/100 · '
            f'{_e(_evidence_text(x))}</div>'
            f'<dl class="kv">{rows}</dl></article>')


def _kj_block(items):
    ranked = _judgment_pool(items)[:4]
    if not ranked:
        return ('<p class="panel">本期入选条目的分析结论均为「无商业信号」：没有客户、预算、价格或采购迹象。'
                '本节不设关键判断；条目仍保留在附录 A 供追溯，不作为行动依据。</p>')
    out = []
    for i, x in enumerate(ranked, 1):
        summary = _one_line((x.get('analysis') or {}).get('summary_zh') or x.get('title', ''), 140)
        implication = _implication(x)
        rows = (_kv('判断', _e(summary)) + _kv('依据', _e(_evidence_basis(x)))
                + (_kv('影响', _e(implication)) if implication else '')
                + _kv('置信度', _e(_confidence(x))))
        out.append(f'<div class="item"><div class="tag">KJ{i}</div>'
                   f'<h3>{_e(_action_title(x))}</h3><dl class="kv">{rows}</dl></div>')
    rest = len(_shown(items)) - len(ranked)
    tail = (f'<p class="muted" style="margin-top:12px;">另有 {rest} 条入选条目没有可识别的商业信号'
            '（评测、预告、纯技术动态），保留在附录 A 供追溯，不进入行动层。</p>') if rest > 0 else ''
    return f'<div class="kj">{"".join(out)}</div>{tail}'


def _actions_block(items):
    rows = _next_actions(items)
    if not rows:
        return '<p class="panel">本期没有达到可执行程度的条目；维持监测，不启动新动作。</p>'
    out = ['<ol class="ol">']
    for step, done, basis in rows:
        out.append(f'<li><div><div class="step">{_e(step)}</div>'
                   f'<div class="done">完成标准：{_e(done)} · 依据：{_e(basis)}</div></div></li>')
    out.append('</ol>')
    return ''.join(out)


def _hypotheses_block(items):
    rows = _hypotheses(items)
    note = ('<p class="muted" style="margin:0 0 10px;">以下是分析给出、但尚未被证据支持的推断。'
            '不作为结论使用。</p>')
    if not rows:
        return note + '<p class="panel">无。</p>'
    body = ''.join(
        f'<div class="item"><span class="tag">H{i}</span> <span class="t">{_e(text)}</span>'
        f'<div class="m">依据 {_e(basis)} · 置信度 {_e(conf)} · 出自《{_e(title)}》</div></div>'
        for i, (text, basis, conf, title) in enumerate(rows, 1))
    return note + f'<div class="hy">{body}</div>'


def _risks_block(items):
    rows = _risks(items)
    return '<ul class="risk">' + ''.join(f'<li>{_e(row)}</li>' for row in rows) + '</ul>'


def _watchlist_block(items):
    rows = _watch_rows(items)
    if not rows:
        return '<p class="panel">本期没有需要单独设触发条件的观察项。</p>'
    body = ''.join(f'<tr><td>{_e(topic)}</td><td>{_e(trigger)}</td><td class="mono">{_e(score)}</td></tr>'
                   for topic, trigger, score in rows)
    return ('<table><thead><tr><th>主题</th><th>触发条件</th><th>当前评分</th></tr></thead>'
            f'<tbody>{body}</tbody></table>')


def _rules_html(stats):
    weights = stats.get('lane_weights') or {}
    if not weights:
        thresholds = stats.get('thresholds') or {}
        return (f'阈值 优先 {_e(thresholds.get("priority", "—"))} / 观察 {_e(thresholds.get("watch", "—"))}。'
                '初筛分数只表示相对优先级。')
    parts = []
    for lane in sorted(weights):
        items = ' · '.join(f'{_e(WEIGHT_LABEL.get(k, k))} {_e(v)}' for k, v in weights[lane].items())
        thresholds = (stats.get('lane_thresholds') or {}).get(lane) or {}
        gate = (f'（优先 {_e(thresholds.get("priority", "—"))} / 观察 {_e(thresholds.get("watch", "—"))}）'
                if thresholds else '')
        parts.append(f'{_e(lane)} 通道 {items}{gate}')
    return '；'.join(parts) + '。初筛分数只表示相对优先级，不同通道之间不可直接比较。'


def _audit_html(stats):
    issues = stats.get('source_issues') or []
    if not issues:
        return '本轮没有登记层面的阻塞问题。'
    rows = [f"[{i.get('severity', 'info')}] {i.get('source_id', '')} · {i.get('code', '')}：{i.get('message', '')}"
            for i in issues[:12]]
    return '<br>'.join(_e(r) for r in rows)


def _watch_block(watch):
    """Weak signals: kept in the library, never in the reading area."""
    limit = int(watch.get('limit') or 8)
    total = (int((watch.get('opportunities') or {}).get('count') or 0)
             + int((watch.get('numeric_without_claims') or {}).get('count') or 0)
             + int((watch.get('candidate_links') or {}).get('count') or 0))
    if total == 0 and not watch.get('cap_unprocessed'):
        return '<p class="muted">本轮没有降级信号。</p>'
    out = ['<p class="muted" style="margin:0 0 10px;">口径：这些条目保留在库中并参与追溯，'
           '不进入主阅读区；弱信号不等于事实，也不计入发布门禁。</p>']

    def group(title, count, items, line):
        shown = items[:limit]
        rows = ''.join(line(i) for i in shown) or '<div>无。</div>'
        more = (f'<div class="muted" style="margin-top:4px;">另有 {count - len(shown)} 条，见归档 JSON。</div>'
                if count > len(shown) else '')
        return (f'<div style="margin-top:12px;"><div style="font-size:12.5px;font-weight:700;">'
                f'{_e(title)}：{count}</div><div class="muted">{rows}</div>{more}</div>')

    opps = watch.get('opportunities') or {}
    records = int(opps.get('records') or opps.get('count') or 0)
    titles = int(opps.get('count') or 0)
    note = f'（原始 {records} 条记录，同一文章重分析会生成多条）' if records > titles else ''
    out.append(group('低置信 Opportunity' + note + '（仅 signal_detected，未经问题/买方/付费验证）',
                     titles, opps.get('items') or [],
                     lambda i: f'<div>[{_e(display.label(i.get("tier"), i.get("reason")))}] {_e(i.get("title"))}'
                               f' · confidence {float(i.get("confidence") or 0):.2f} · 追溯链接 {i.get("links")}'
                               + (f' · 同标题 {(i.get("duplicates") or 0) + 1} 条' if i.get("duplicates") else '')
                               + '</div>'))
    nums = watch.get('numeric_without_claims') or {}
    out.append(group('有数字但未形成可核验主张', int(nums.get('count') or 0), nums.get('items') or [],
                     lambda i: f'<div>[{_e(display.label(i.get("tier"), i.get("reason")))}] {_e(i.get("title"))}'
                               f'（数字候选 {i.get("candidates")} 个）</div>'))
    links = watch.get('candidate_links') or {}
    out.append(group('可能相关事件（未确认合并，不作为同一事件）', int(links.get('count') or 0),
                     links.get('items') or [],
                     lambda i: f'<div>[{_e(display.label(i.get("tier"), i.get("reason")))}] {_e(i.get("left"))} ↔ {_e(i.get("right"))}'
                               f'（依据 {_e(i.get("basis"))} · {float(i.get("confidence") or 0):.2f}）</div>'))
    cap = int(watch.get('cap_unprocessed') or 0)
    if cap:
        out.append(f'<div class="muted" style="margin-top:12px;">N0–N5 本轮上限外：{cap} 篇已分析文章未进入'
                   '主张提取，下一轮继续（不是丢弃）。</div>')
    return ''.join(out)


def render_html(items, stats, date_label=None, include_appendix=True):
    date_label = date_label or datetime.now().astimezone().strftime('%Y-%m-%d')
    counts = stats.get('counts', {})
    strong = sum(1 for x in items if _pay_strong(x))
    shown = _shown(items)
    deferred = _deferred(items)
    filtered = [x for x in items if x.get('status') == 'filtered']
    reason = stats.get('empty_reason') or empty_reason(stats)
    fetched = stats.get('fetched', stats.get('article_count', 0))
    analyzed = stats.get('analyzed', stats.get('analyzed_count', 0))
    skipped = stats.get('skipped', 0)
    coverage = stats.get('coverage')

    parts = ['<header class="cover">',
             '<div class="brand">OPPORTUNITY RADAR</div>',
             '<h1>商业机会情报简报</h1>',
             f'<div class="sub">证据优先 · 结论先行 · {_e(date_label)}</div>',
             '<div class="rule"></div>',
             '<div class="meta">',
             f'<div><div class="k">报告编号</div><div class="v">OR-{_e(date_label.replace("-", ""))}</div></div>',
             f'<div><div class="k">生成时间</div><div class="v">{_e(datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"))}</div></div>',
             f'<div><div class="k">本轮获取</div><div class="v">{_e(fetched)} 篇 · 新增分析 {_e(analyzed)} 篇</div></div>',
             '<div><div class="k">用途</div><div class="v">个人非商业 · 内部参考</div></div>',
             '</div></header>',
             '<div class="kpi">',
             f'<div class="cell"><div class="n">{len(shown)}</div><div class="l">入选条目</div></div>',
             f'<div class="cell"><div class="n">{counts.get("priority", 0)}</div><div class="l">优先验证</div></div>',
             f'<div class="cell"><div class="n">{counts.get("watch", 0)}</div><div class="l">持续观察</div></div>',
             f'<div class="cell"><div class="n">{("—" if coverage is None else f"{coverage:.0%}")}</div><div class="l">分析覆盖率</div></div>',
             '</div>',
             '<div class="wrap">']

    if stats.get('sample_mode'):
        parts.append('<div class="warn" style="margin-top:24px;"><strong>离线演示数据：</strong>'
                     '以下内容仅用于展示报告结构，不代表真实来源、用户需求或商业机会。</div>')

    parts.append(_section(1, '执行摘要（核心判断）', 'Executive summary'))
    parts.append(f'<p class="governing">{_e(decision_headline(items, stats))}</p>')
    note = ('样例仅用于演示字段和版式，不构成对真实需求的判断。' if stats.get('sample_mode')
            else management_note(items))
    parts.append(f'<p class="note">{_e(note)}</p></section>')

    parts.append(_section(2, '关键判断', 'Key judgments'))
    parts.append('<p class="muted" style="margin:-4px 0 10px;">按可执行性、通道与信号分排序；'
                 '每条只回答一个问题：这条信息是否改变我们的行动。</p>')
    parts.append(_kj_block(items) + '</section>')

    parts.append(_section(3, '建议行动', 'Next actions'))
    parts.append(_actions_block(items) + '</section>')

    parts.append(_section(4, '待验证假设', 'Hypotheses'))
    parts.append(_hypotheses_block(items) + '</section>')

    parts.append(_section(5, '风险与反证', 'What would falsify this'))
    parts.append(_risks_block(items) + '</section>')

    parts.append(_section(6, '监测清单', 'Watch list'))
    parts.append(_watchlist_block(items) + '</section>')

    parts.append(_section(7, '证据与方法', 'Basis of preparation'))
    parts.append(_chart_block('处理漏斗（条目数）', funnel(stats)))
    disclosed = disclosure(stats)
    if disclosed:
        parts.append(f'<div class="warn" style="margin-top:14px;"><strong>运行完整性：</strong>{_e(disclosed)}</div>')
    parts.append(_chart_block('通道分布（分析条目）',
                              [(LANE_LABEL[r['lane']][:8], r['items'], f"入选 {r['shown']}") for r in lane_breakdown(items)]))
    line_rows = [(INTELLIGENCE_LINE_LABEL.get(str(k), str(k))[:10], v, '来源声明') for k, v in summarize(items)]
    if line_rows:
        parts.append(_chart_block('情报主线（分析条目）', line_rows))
    parts.append(_chart_block('证据强度（条目数）',
                              [(STATE_LABEL.get(e['state'], e['state']), e['count']) for e in evidence_breakdown(items)]))
    parts.append(f'<p class="muted" style="margin-top:10px;">{_e(denominator_note(stats))}</p>')
    present = {_state(x) for x in items}
    meanings = [STATE_MEANING[st] for st in EVIDENCE_STATES if st in present and st in STATE_MEANING]
    if meanings:
        parts.append(f'<p class="muted" style="margin-top:4px;"><strong>证据口径：</strong>{_e(" ".join(meanings))}</p>')
    parts.append('<div class="panel" style="margin-top:14px;">'
                 f'<div>模型 {_e(stats.get("model") or "未记录")} · 提示词 v{_e(stats.get("prompt_version") or "未记录")}'
                 f'（{_e(stats.get("prompt_hash") or "hash未记录")}）· 规则 {_e(stats.get("rules_version", "v2"))}</div>'
                 f'<div style="margin-top:4px;">本轮获取 {_e(fetched)} 篇 · 新增分析 {_e(analyzed)} 篇'
                 + (f' · 已有结果跳过 {_e(skipped)} 篇' if skipped else '')
                 + f' · 入选 {len(shown)} 条 · 明确付费证据 {strong} 条</div></div></section>')

    if include_appendix:
        parts.append(_section(8, '附录 A · 条目明细', 'Evidence appendix'))
        representatives, _siblings = group_by_event(shown)
        if representatives:
            for x in sorted(representatives, key=_order_key):
                parts.append(_finding(x))
                note = event_summary_lines(x)
                if note:
                    parts.append('<div class="muted" style="margin:-8px 0 14px;">'
                                 + '<br>'.join(_e(line.strip()) for line in note) + '</div>')
        else:
            parts.append(f'<p class="panel">{_e(reason)}</p>')
        parts.append('</section>')

        parts.append(_section(9, '附录 B · 未纳入与失败', 'Excluded'))
        if deferred:
            rows = ''.join(
                f'<tr><td>[{_e(STATUS_LABEL.get(x.get("status"), x.get("status")))} · {_e(x.get("score", 0))}/100] '
                f'{_e(x.get("title", ""))}</td><td class="mono">{_e(x.get("source_name", "Unknown"))}</td></tr>'
                for x in sorted(deferred, key=lambda v: (-v.get('score', 0), v.get('title', ''))))
            parts.append(f'<p class="muted" style="margin:0 0 8px;">本期未纳入分发（来源单期配额）：'
                         f'{len(deferred)} 条，原始判断保留如下，不代表价值较低。</p>'
                         f'<table><thead><tr><th>条目</th><th>来源</th></tr></thead><tbody>{rows}</tbody></table>')
        if filtered:
            for key, label in REASON_LABEL.items():
                group = [x for x in filtered if x.get('filter_reason') == key]
                if not group:
                    continue
                rows = ''.join(f'<tr><td>[{x.get("score", 0)}/100] {_e(x.get("title", ""))}</td></tr>'
                               for x in group[:10])
                parts.append(f'<p class="muted" style="margin:14px 0 8px;"><strong>{_e(label)}：{len(group)} 篇</strong></p>'
                             f'<table><tbody>{rows}</tbody></table>')
        if not deferred and not filtered:
            parts.append('<p class="panel">无。</p>')
        watch_list = stats.get('watchlist')
        if watch_list:
            parts.append('<div style="margin-top:22px;"><div class="muted" style="font-weight:700;color:var(--ink);">'
                         '弱信号（保留在库中，不进入主阅读区）</div></div>')
            parts.append(_watch_block(watch_list))
        parts.append('</section>')

        parts.append(_section(10, '附录 C · 来源与数据源', 'Sources'))
        src_rows = [(r['source'], r['items'], f"引文 {r['located']}/{r['evidence']}" if r['evidence'] else '无引文')
                    for r in source_breakdown(items)]
        parts.append(_chart_block('来源贡献（分析条目）', src_rows))
        sources = ', '.join(f'{k} {v}' for k, v in Counter(x.get('source_name', 'Unknown') for x in items).most_common()) or '无'
        parts.append(f'<p class="muted" style="margin-top:10px;"><strong>来源分布：</strong>{_e(sources)}</p>')
        quality = Counter(_evidence_text(x) for x in items)
        q = ', '.join(f'{k} {v}' for k, v in quality.most_common()) or '无'
        parts.append(f'<p class="muted" style="margin-top:4px;"><strong>数据质量：</strong>证据等级分布 {_e(q)}。'
                     '仅标题或无法在原文中定位的摘录不能作为已验证需求。</p>')
        conflict_lines = stats.get('conflicts') or []
        if conflict_lines:
            body = '<br>'.join(_e(line.strip()) for line in conflict_lines)
            parts.append(f'<div class="warn" style="margin-top:12px;"><strong>数据冲突（记录，不判定对错）：</strong>'
                         f'<br>{body}</div>')
        parts.append(f'<p class="muted" style="margin-top:10px;"><strong>来源审计：</strong>{_audit_html(stats)}</p>')
        parts.append(f'<p class="muted" style="margin-top:4px;"><strong>评分规则：</strong>'
                     f'版本 {_e(stats.get("rules_version", "v2"))}。{_rules_html(stats)}</p>')
        parts.append('</section>')

    else:
        parts.append(_section(8, '附录 · 本地存档', 'Appendix archived'))
        parts.append(f'<p class="panel">{_e(appendix_note(items, stats))}</p></section>')

    parts.append('<div class="foot">免责声明：本报告为自动化初筛，不构成商业、法律或投资结论。'
                 '营收、利润、市场规模和法律许可等主张必须核对原始来源及独立证据。</div>')
    parts.append('</div>')

    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_e("Opportunity Radar · 商业机会情报简报 · " + date_label)}</title>'
            f'<style>{STYLE}</style></head><body><div class="sheet">'
            + ''.join(parts) + '</div></body></html>')
