"""Units, scales and numeric comparison for claim verification.

Deterministic only. Nothing here guesses: a number it cannot parse is `None`, a unit it does
not know is `unknown`, and a comparison it cannot make is refused rather than approximated.

The one rule that matters most: a percentage and a percentage point are different
quantities. 5% -> 6% is a one-percentage-point rise and a 20% rise; a claim that conflates
them is wrong even when both numbers appear in the text.
"""
from __future__ import annotations

import re

PERCENT = '%'
PERCENT_POINT = 'pp'

# Words that scale a number. Ordered longest-first so "billion" wins over "bn".
SCALES = (
    ('trillion', 1e12), ('billion', 1e9), ('million', 1e6), ('thousand', 1e3),
    ('tn', 1e12), ('bn', 1e9), ('mn', 1e6), ('k', 1e3),
    ('万亿', 1e12), ('亿', 1e8), ('万', 1e4),
)

CURRENCIES = ('USD', 'EUR', 'GBP', 'JPY', 'CNY', 'RMB', 'HKD', 'TWD', 'KRW', 'INR', 'CAD', 'AUD',
              'CHF', 'SEK', 'NOK', 'DKK', 'SGD', 'NZD', 'BRL', 'MXN', 'ZAR')
CURRENCY_SIGNS = {'$': 'USD', '€': 'EUR', '£': 'GBP', '¥': 'JPY', '￥': 'CNY'}

# Physical units a number can carry. The scale word ('thousand') is stripped first, so these
# names are the base unit the claim's unit is compared against.
UNIT_WORDS = (
    (re.compile(r'^[ 	]*megawatt[ 	-]?hours?(?![a-z])|^[ 	]*mwh(?![a-z])', re.I), 'megawatthours'),
    (re.compile(r'^[ 	]*gwh(?![a-z])', re.I), 'gwh'),
    (re.compile(r'^[ 	]*kwh(?![a-z])', re.I), 'kwh'),
    (re.compile(r'^[ 	]*tonnes?(?![a-z])|^[ 	]*metric tons?(?![a-z])', re.I), 'tonnes'),
    (re.compile(r'^[ 	]*barrels?(?![a-z])|^[ 	]*bbl(?![a-z])', re.I), 'barrels'),
    (re.compile(r'^[ 	]*shares?(?![a-z])', re.I), 'shares'),
    (re.compile(r'^[ 	]*cells?(?![a-z])', re.I), 'cells'),
    (re.compile(r'^[ 	]*fps(?![a-z])', re.I), 'fps'),
    (re.compile(r'^[ 	]*km(?![a-z])', re.I), 'kilometres'),
    (re.compile(r'^[ 	]*cm(?![a-z])', re.I), 'centimetres'),
    (re.compile(r'^[ 	]*mm(?![a-z])', re.I), 'millimetres'),
    (re.compile(r'^[ 	]*metres?(?![a-z])|^[ 	]*meters?(?![a-z])|^[ 	]*m(?![a-z])', re.I), 'metres'),
    (re.compile(r'^[ 	]*kilograms?(?![a-z])|^[ 	]*kg(?![a-z])', re.I), 'kilograms'),
)

PERCENT_WORDS = ('percent', 'per cent', '%', '百分比', '％')
POINT_WORDS = ('percentage point', 'percentage points', 'pp', 'pct point', '百分点', '个百分点')

# Units that mean "energy, scaled". Verification compares within a family and never across.
UNIT_FAMILY = {code.lower(): 'currency' for code in CURRENCIES}
UNIT_FAMILY.update({
    '%': 'percent', 'pp': 'percent_point',
    'megawatthours': 'energy', 'gwh': 'energy', 'kwh': 'energy', 'mwh': 'energy',
    'tonnes': 'mass', 'kilograms': 'mass', 'barrels': 'volume', 'shares': 'count',
    'cells': 'count', 'fps': 'rate', 'metres': 'length', 'kilometres': 'length',
    'centimetres': 'length', 'millimetres': 'length',
})

# A number never swallows a bare space: '08 70937.35' is two numbers, not 870937.35.
# The trailing guard rejects only another digit: "500bn" and "$1tn" attach the scale
# directly, and a letter after the number is handled by the scale/unit lookups below.
NUMBER = re.compile(r'(?<![\w.])(?:[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-+]?\d+(?:\.\d+)?)(?!\d)')
SCALE_AFTER = re.compile(
    r'^\s*(trillion|billion|million|thousand|tn|bn|mn|k|万亿|亿|万)\b', re.I)
PERCENT_AFTER = re.compile(r'^\s*(%|percent\b|per cent\b|％|pp\b|percentage points?\b|百分点|个百分点)', re.I)


def normalize_unit(unit):
    """Canonical spelling for a unit string; unknown units are returned trimmed, not guessed."""
    text = re.sub(r'\s+', ' ', str(unit or '').strip().lower())
    if text in ('', 'none', 'n/a', 'unknown'):
        return ''
    if text in PERCENT_WORDS or text == '%':
        return PERCENT
    if text in POINT_WORDS:
        return PERCENT_POINT
    for code in CURRENCIES:
        if text == code.lower():
            return code
    return text


def unit_family(unit):
    base, _scale = split_unit(unit)
    return UNIT_FAMILY.get(base.lower(), 'unknown')


def parse_number(raw):
    """'1,234.5' -> 1234.5; '(1.2)' -> -1.2; anything else -> None."""
    text = str(raw or '').strip()
    if not text:
        return None
    negative = text.startswith('(') and text.endswith(')')
    if negative:
        text = text[1:-1]
    text = text.replace(',', '').replace(' ', '').replace(' ', '')
    try:
        value = float(text)
    except ValueError:
        return None
    return -value if negative else value


def quantities(text):
    """[(value, unit)] for every number in `text`, with the scale and unit that follow it.

    The unit is taken from the text right after the number ('12 million', '5%'), because
    that is how prose attaches it; a currency sign before the number is picked up too.
    """
    out = []
    for match in NUMBER.finditer(str(text or '')):
        value = parse_number(match.group(0))
        if value is None:
            continue
        tail = text[match.end():match.end() + 40]
        scale = 1.0
        scaled = SCALE_AFTER.match(tail)
        if scaled:
            word = scaled.group(1).lower()
            scale = dict((word, factor) for word, factor in SCALES).get(word, 1.0)
            tail = tail[scaled.end():]
        unit = ''
        percent = PERCENT_AFTER.match(tail)
        if percent:
            token = percent.group(1).lower()
            unit = PERCENT_POINT if token in POINT_WORDS else PERCENT
        else:
            for code in CURRENCIES:
                if re.match(r'^\s*' + code + r'\b', tail, re.I):
                    unit = code
                    break
            else:
                for pattern, name in UNIT_WORDS:
                    if pattern.match(tail):
                        unit = name
                        break
                else:
                    for sign, code in CURRENCY_SIGNS.items():
                        if sign in text[:match.start()][-3:]:
                            unit = code
                            break
        out.append((value * scale, unit))
    return out


def same_number(left, right, rel_tolerance=1e-6):
    if left is None or right is None:
        return False
    if left == right:
        return True
    scale = max(abs(left), abs(right))
    return scale > 0 and abs(left - right) / scale <= rel_tolerance


def split_unit(unit):
    """('USD million',) -> ('USD', 1e6). A scale word inside a unit is part of the unit."""
    canonical = normalize_unit(unit)
    if not canonical:
        return '', 1.0
    for word, factor in SCALES:
        # 'USD million' scales after the unit, 'thousand megawatthours' scales before it.
        if canonical.startswith(word + ' '):
            return normalize_unit(canonical[len(word):]), factor
        if canonical.endswith(' ' + word) or canonical == word:
            return normalize_unit(canonical[:len(canonical) - len(word)]), factor
    return canonical, 1.0


def convert(value, from_unit, to_unit):
    """Value in `to_unit`, or None when the conversion would be a guess.

    Only same-family conversions with a known scale are allowed; no exchange rates, no
    family hopping (a percentage is not a percentage point, USD is not a share count).
    """
    if value is None:
        return None
    from_base, from_scale = split_unit(from_unit)
    to_base, to_scale = split_unit(to_unit)
    if from_base == to_base:
        return value * from_scale / to_scale
    if unit_family(from_base) == unit_family(to_base) != 'unknown' and from_base == to_base:
        return value * from_scale / to_scale
    return None


def percent_or_point(unit):
    canonical = normalize_unit(unit)
    if canonical == PERCENT:
        return 'percent'
    if canonical == PERCENT_POINT:
        return 'percentage_point'
    return ''
