"""The structured claim contract (R2, version r2-v1).

A claim is a sentence reduced to fields: who, what measure, what value, in what unit, over
what period, compared how. The contract defines those fields, their vocabulary and what a
non-compliant value does - which is never "drop the article". A bad field is blanked and
recorded as a deviation; the rest of the claim survives and the verification step can still
call it unverifiable.

Nothing here talks to a model. `parse_claims` accepts a payload shaped like the one a later
prompt will produce, so the contract, its tests and its rules version can be reviewed before
any production prompt changes.
"""
from __future__ import annotations

import re

from . import units

CONTRACT_VERSION = 'r2-v1'

KINDS = ('fact', 'source_interpretation', 'system_inference', 'hypothesis', 'forecast',
         'opinion', 'unknown')
COMPARISONS = ('level', 'year_over_year', 'quarter_over_quarter', 'month_over_month',
               'period_change', 'percentage_point_change', 'share', 'unknown')
SEASONALITY = ('seasonally_adjusted', 'not_seasonally_adjusted', 'unknown')
REVISION = ('original', 'revised', 'preliminary', 'unknown',
            'amendment', 'subsequent_comparative')

MAX_SUBJECT = 200
MAX_PREDICATE = 80
MAX_TEXT = 500

PERIOD_PATTERNS = (
    re.compile(r'^\d{4}$'),
    re.compile(r'^\d{4}-\d{2}$'),
    re.compile(r'^\d{4}-\d{2}-\d{2}$'),
    re.compile(r'^\d{4}-Q[1-4]$'),
    re.compile(r'^\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2}$'),
    re.compile(r'^\d{4}/\d{4}$'),
)


def _text(value, limit):
    return re.sub(r'\s+', ' ', str(value or '').strip())[:limit]


def _deviation(field, reason, value):
    return {'field': field, 'reason': reason, 'value': str(value)[:120]}


def valid_period(period):
    text = str(period or '').strip()
    return bool(text) and any(pattern.match(text) for pattern in PERIOD_PATTERNS)


def normalize(payload):
    """(claim, deviations). Every field is validated on its own; nothing is inferred."""
    if not isinstance(payload, dict):
        raise ValueError('claim must be an object')
    deviations = []
    claim = {}

    subject = _text(payload.get('subject'), MAX_SUBJECT)
    if not subject:
        deviations.append(_deviation('subject', 'missing', payload.get('subject')))
    claim['subject'] = subject

    predicate = _text(payload.get('predicate'), MAX_PREDICATE)
    if not predicate:
        deviations.append(_deviation('predicate', 'missing', payload.get('predicate')))
    claim['predicate'] = predicate

    kind = str(payload.get('kind') or 'unknown').strip().lower()
    if kind not in KINDS:
        deviations.append(_deviation('kind', 'unknown_value', kind))
        kind = 'unknown'
    claim['kind'] = kind

    raw_value = payload.get('value_num')
    value = None
    if raw_value is not None and str(raw_value).strip() != '':
        value = raw_value if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool) \
            else units.parse_number(raw_value)
        if value is None:
            deviations.append(_deviation('value_num', 'not_numeric', raw_value))
    claim['value_num'] = float(value) if isinstance(value, (int, float)) else None
    claim['value_text'] = _text(payload.get('value_text'), MAX_TEXT)

    unit = units.normalize_unit(payload.get('unit'))
    if unit and units.unit_family(unit) == 'unknown':
        deviations.append(_deviation('unit', 'unknown_unit', unit))
    claim['unit'] = unit

    currency = str(payload.get('currency') or '').strip().upper()
    if currency and currency not in units.CURRENCIES:
        deviations.append(_deviation('currency', 'unknown_currency', currency))
        currency = ''
    if not currency and units.unit_family(unit) == 'currency':
        currency = units.split_unit(unit)[0]
    claim['currency'] = currency

    period = str(payload.get('period') or '').strip()
    if period and not valid_period(period):
        deviations.append(_deviation('period', 'unrecognised_format', period))
        period = ''
    claim['period'] = period

    for field, vocabulary in (('comparison', COMPARISONS), ('seasonality', SEASONALITY),
                              ('revision', REVISION)):
        value = str(payload.get(field) or 'unknown').strip().lower()
        if value not in vocabulary:
            deviations.append(_deviation(field, 'unknown_value', value))
            value = 'unknown'
        claim[field] = value

    claim['region'] = _text(payload.get('region'), 32)
    claim['denominator'] = _text(payload.get('denominator'), 120)
    claim['quote'] = _text(payload.get('quote'), 1000)
    if claim['value_num'] is not None and not claim['quote']:
        deviations.append(_deviation('quote', 'missing', ''))
    return claim, deviations


def parse_claims(payload):
    """(claims, deviations) from {"claims": [...]}. An unusable item costs one claim, not the article."""
    if not isinstance(payload, dict) or not isinstance(payload.get('claims'), list):
        raise ValueError('payload must be an object with a claims list')
    claims, deviations = [], []
    for index, item in enumerate(payload['claims']):
        try:
            claim, item_deviations = normalize(item)
        except ValueError:
            deviations.append({'ordinal': index + 1, 'field': '*', 'reason': 'not_an_object', 'value': ''})
            continue
        for deviation in item_deviations:
            deviations.append(dict(deviation, ordinal=index + 1))
        if not claim['subject'] or not claim['predicate']:
            deviations.append({'ordinal': index + 1, 'field': '*', 'reason': 'claim_without_subject_or_predicate', 'value': ''})
            continue
        claim['ordinal'] = index + 1
        claims.append(claim)
    return claims, deviations


def contract_summary():
    """What the contract promises, for the G6 review material."""
    return {
        'version': CONTRACT_VERSION,
        'kinds': list(KINDS),
        'comparisons': list(COMPARISONS),
        'seasonality': list(SEASONALITY),
        'revision': list(REVISION),
        'period_formats': ['YYYY', 'YYYY-MM', 'YYYY-MM-DD', 'YYYY-Qn', 'YYYY-MM-DD/YYYY-MM-DD', 'YYYY/YYYY'],
        'required': ['subject', 'predicate', 'kind'],
        'degrades_to_deviation': ['value_num', 'unit', 'currency', 'period', 'comparison',
                                  'seasonality', 'revision', 'quote'],
    }
