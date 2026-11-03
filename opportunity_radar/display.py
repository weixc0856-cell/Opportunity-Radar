"""Display tiers: discovery keeps every signal, the digest decides how loudly to say it.

The pipeline deliberately keeps weak material — skeleton claims, `signal_detected`
opportunities, unconfirmed event links, numbers that N2–N5 could not turn into a claim.
Filtering it at discovery would delete information a later run or a human could
corroborate; filtering it at display would hide it. These functions are pure so the three
classes stay testable without a database or a model, and they never change scoring, the
publication gate, or what is stored.

    L0  高置信  verified claim / promoted opportunity / accepted link
    L1  中置信  located but not verified (skeleton or unverified numeric)
    L2  弱信号  title-level, signal-only, candidate link, numbers without a claim
    L3  已过滤  not shown (kept in the database; scoring decides this, not this module)
"""
from __future__ import annotations

TIERS = ('L0', 'L1', 'L2', 'L3')
TIER_LABEL = {'L0': '高置信', 'L1': '中置信', 'L2': '弱信号', 'L3': '已过滤'}

REASON_LABEL = {
    'verified': '已核验',
    'skeleton_only': '仅骨架主张（有定位，无期限/数值）',
    'unverified_numeric': '有定位但未核验',
    'no_locator': '无证据定位',
    'signal_only': '仅 signal_detected，未经人工提升',
    'promoted': '已人工提升',
    'candidate_link': '候选关联，未确认合并',
    'accepted_link': '已确认关联',
    'no_claim': '有数字候选但未形成 r2-v4 Claim',
    'cap_reached': '本轮 N0–N5 上限未处理',
}


def claim_tier(record):
    """(tier, reason) for one stored claim or event-card claim item."""
    record = record or {}
    state = str(record.get('verification_state') or '').strip().lower()
    if state == 'verified':
        return 'L0', 'verified'
    locator = record.get('locator_json')
    has_locator = bool(locator) and str(locator).strip() not in ('', '{}', 'null', 'None')
    if has_locator or record.get('evidence_id'):
        return 'L1', ('skeleton_only' if state == 'unverifiable'
                      else 'unverified_numeric')
    return 'L2', 'no_locator'


def opportunity_tier(record):
    """(tier, reason) for one Opportunity row.

    `signal_detected` is the automatic discovery state; it stays L2 until a human
    promotes it, regardless of how convincing the article read.
    """
    state = str((record or {}).get('validation_state') or 'signal_detected').lower()
    if state == 'signal_detected':
        return 'L2', 'signal_only'
    return 'L0', 'promoted'


def link_tier(record):
    """(tier, reason) for one event/claim link row."""
    status = str((record or {}).get('status') or 'candidate').lower()
    return ('L2', 'candidate_link') if status == 'candidate' else ('L1', 'accepted_link')


def label(tier, reason):
    """One short marker for a report line, e.g. `L1·中置信·有定位但未核验`."""
    return f'{tier}·{TIER_LABEL.get(tier, tier)}·{REASON_LABEL.get(reason, reason)}'
