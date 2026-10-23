"""Intelligence mainlines: why a source is monitored at all.

The A/B/C editorial lanes decide how an item is judged (company news vs buyer pain vs
technical tracking). The mainlines answer a different question — policy, macro data,
corporate disclosure, industry, news, technology — and are orthogonal to scoring. A
source may serve several lines; a line may be served by several sources.

This module is deliberately tiny: it parses and orders declarations, and nothing here
is read by `scoring.py`, `evidence.py` or `lanes.py`.
"""
import re

# Stable codes. Labels are for humans and may change; codes are what the registry stores.
POLICY = 'policy_regulation'
MACRO = 'macro_economy'
CORP = 'corporate_capital'
INDUSTRY = 'industry_supply_chain'
NEWS = 'international_news'
TECH = 'technology_research'
OPPORTUNITY = 'market_opportunity'
ENGINEERING = 'engineering_specialist'
MAINTENANCE = 'system_maintenance'

INTELLIGENCE_LINES = (POLICY, MACRO, CORP, INDUSTRY, NEWS, TECH, OPPORTUNITY, ENGINEERING, MAINTENANCE)

INTELLIGENCE_LINE_LABEL = {
    POLICY: '政策与监管',
    MACRO: '宏观经济与统计',
    CORP: '企业经营与资本配置',
    INDUSTRY: '产业、能源与供应链',
    NEWS: '国际新闻与调查报道',
    TECH: '科技、研究与商业机会',
    OPPORTUNITY: '市场需求与机会',
    ENGINEERING: '工程与专业技术',
    MAINTENANCE: '系统维护',
}

# Lines that must never compete with external intelligence for the daily briefing.
MAINTENANCE_LINES = frozenset({MAINTENANCE})


def _src(source, name):
    if source is None:
        return ''
    if isinstance(source, dict):
        return source.get(name) or ''
    return getattr(source, name, '') or ''


def lines_of(source):
    """Declared mainlines for a source, in canonical order. Empty when undeclared.

    Accepts the same separators as `editorial_lanes`, so one registry value can carry
    several lines. Unknown tokens are preserved in order but dropped here; the audit
    reports them rather than letting a typo silently look like a valid declaration.
    """
    raw = str(_src(source, 'intelligence_lines') or '').lower()
    found = {t for t in re.split(r'[\s,;|/]+', raw) if t}
    return tuple(line for line in INTELLIGENCE_LINES if line in found)


def labels_of(source):
    return tuple(INTELLIGENCE_LINE_LABEL[line] for line in lines_of(source))


def summarize(items):
    """Count analysed items per mainline, using each item's declared source lines.

    An item carries the `intelligence_lines` string copied from its source at analysis
    time. Items from unregistered or undeclared sources are counted under '(undeclared)'
    rather than guessed into a line.
    """
    counts = {}
    for item in items or []:
        lines = lines_of(item) or ('(undeclared)',)
        for line in lines:
            counts[line] = counts.get(line, 0) + 1
    order = {line: i for i, line in enumerate(INTELLIGENCE_LINES)}
    return sorted(counts.items(), key=lambda kv: (order.get(kv[0], len(order)), kv[0]))
