"""Publication gate for one run.

An analysis that failed and an analysis that was never attempted because the model went
away are different events, but both mean the issue is incomplete. Coverage counts the
articles this run meant to analyse and how many of them produced a stored analysis, so
neither can hide behind the other.

Thresholds are the ones approved for R0:
    PASS                  coverage >= 0.8
    PASS_WITH_LIMITATIONS 0.5 <= coverage < 0.8
    HOLD                  coverage < 0.5
A blocking integrity fault forces HOLD whatever the coverage, because a run that could
not finish its own bookkeeping must not be presented as a normal issue.
"""
from __future__ import annotations

PASS = 'PASS'
PASS_WITH_LIMITATIONS = 'PASS_WITH_LIMITATIONS'
HOLD = 'HOLD'
STATUSES = (PASS, PASS_WITH_LIMITATIONS, HOLD)
LABEL = {PASS: 'PASS', PASS_WITH_LIMITATIONS: 'PASS_WITH_LIMITATIONS', HOLD: 'HOLD'}

BLOCKING_CAUSES = frozenset({'integrity', 'model_unavailable'})
DEFAULT_MIN_COVERAGE = 0.8
DEFAULT_HOLD_BELOW = 0.5

CAUSE_LABEL = {
    'connect_reset': '连接重置',
    'connect_refused': '连接被拒绝',
    'timeout': '请求超时',
    'http_429': '限流 429',
    'http_5xx': '服务端错误 5xx',
    'http_4xx': '请求错误 4xx',
    'schema': '输出不符合契约',
    'circuit_open': '熔断未尝试',
    'integrity': '运行完整性故障',
    'model_unavailable': '模型不可用',
    'unknown': '未分类错误',
}


def coverage(analyzed, queued):
    """Share of the articles this run queued that ended with a stored analysis.

    A run with nothing to analyse has full coverage: a complete run that finds no new
    signal must stay publishable, and that is exactly the case coverage must not punish.
    """
    if queued <= 0:
        return 1.0
    return max(0.0, min(1.0, float(analyzed) / float(queued)))


def decide(analyzed, queued, integrity_fault=False,
           min_coverage=DEFAULT_MIN_COVERAGE, hold_below=DEFAULT_HOLD_BELOW):
    if integrity_fault:
        return HOLD
    cov = coverage(analyzed, queued)
    if cov >= min_coverage:
        return PASS
    if cov >= hold_below:
        return PASS_WITH_LIMITATIONS
    return HOLD


def publishable(status):
    return status in (PASS, PASS_WITH_LIMITATIONS)


def blocking(causes):
    """True when a recorded failure reason forbids publication regardless of coverage."""
    return any(c in BLOCKING_CAUSES and n for c, n in (causes or {}).items())


def cause_text(causes):
    """Deterministic one-line summary; an empty run says so instead of printing nothing."""
    items = [(c, n) for c, n in (causes or {}).items() if n]
    if not items:
        return '无'
    order = list(CAUSE_LABEL)
    items.sort(key=lambda kv: (order.index(kv[0]) if kv[0] in order else len(order), kv[0]))
    return '，'.join(f'{CAUSE_LABEL.get(c, c)} {n}' for c, n in items)


def headline_notice(stats):
    """The one sentence a headline must carry when the run did not analyse what it queued."""
    stats = stats or {}
    cov = stats.get('coverage')
    if cov is None or cov >= 1:
        return ''
    analyzed = int(stats.get('analyzed', stats.get('analyzed_count', 0)) or 0)
    queued = int(stats.get('queued', stats.get('analyzed_count', 0)) or 0)
    return f'本轮分析未完整完成：成功 {analyzed}/{queued}（覆盖率 {cov:.0%}）。'


def disclosure(stats):
    """The sentence every incomplete report must carry. None when the run was complete."""
    stats = stats or {}
    cov = stats.get('coverage')
    if cov is None or cov >= 1:
        return None
    analyzed = int(stats.get('analyzed', stats.get('analyzed_count', 0)) or 0)
    queued = int(stats.get('queued', stats.get('analyzed_count', 0)) or 0)
    failed = int(stats.get('failed', stats.get('error_count', 0)) or 0)
    not_attempted = int(stats.get('not_attempted', 0) or 0)
    status = stats.get('publication_status') or ''
    parts = [f'本轮分析覆盖率 {cov:.0%}（成功 {analyzed}/{queued}）']
    if failed:
        parts.append(f'失败 {failed} 篇')
    if not_attempted:
        parts.append(f'熔断后未尝试 {not_attempted} 篇')
    reasons = cause_text(stats.get('failed_causes'))
    if reasons != '无':
        parts.append(f'失败原因：{reasons}')
    if status:
        parts.append(f'发布状态 {LABEL.get(status, status)}')
    parts.append('本报告只覆盖已成功分析的部分，不代表本期全部信息')
    return '；'.join(parts) + '。'
