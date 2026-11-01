"""N1: find every number the text contains, and nothing else.

N1 is deterministic and deliberately shallow. It does not decide what a number means, who it
belongs to, whether it is a level or a change, or whether it is commercially interesting -
those are N2 and N3's questions. It finds numeric expressions, says what lexical class each
one looks like (money, percent, percentage point, quantity, magnitude, date, period, time,
ratio, range, ordinal, identifier, bare, embedded), and records where it came from.

Two rules shape the implementation:

1. Nothing disappears. Every decimal digit in the article belongs to exactly one candidate.
   A digit inside a word or a URL still becomes a candidate, classed `embedded`, so a later
   node has to make an explicit decision about it instead of it silently vanishing. (A
   superscript like the 2 in 'm²' is a unit exponent, not a digit in this sense.)
2. Nothing is computed. `$92.8 billion` becomes value 92.8 with scale billion, not
   92800000000; a percentage point stays distinct from a percent. Parsing and scaling are
   N4's job, and N1 must not pre-empt it with a value a later node cannot audit.

The scan is leftmost-longest: at any position the longest match wins, and a match that
overlaps an accepted one is dropped. A candidate's `raw` is the exact slice of the canonical
text it covers, with offsets into that field and spans back into the raw HTML.
"""
from __future__ import annotations

import re

from . import units

VERSION = 'n1-v1'

_CURRENCY_ALT = '|'.join(sorted((code.lower() for code in units.CURRENCIES),
                                key=len, reverse=True))
_SCALE_FACTOR = dict(units.SCALES)

# A number, optionally preceded by a currency sign or code. The lookbehind keeps the scanner
# out of the middle of an ASCII alphanumeric token; `embedded` below catches what that
# excludes. CJK is deliberately not blocked: '增长了5%' has no space before the figure.
_NUMBER_EXPR = re.compile(
    r'(?<![A-Za-z0-9_.])'
    r'(?:(?:(?P<sign1>[$€£¥￥])|(?P<code1>(?:' + _CURRENCY_ALT + r'))(?![a-z]))\s*)?'
    r'(?P<num>[-+]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?))', re.I)

# 'billion' wins over 'bn'; the CJK scales cannot use \b because CJK characters are word
# characters, so '3.5亿元' would not match at all with a word boundary after 亿.
_SCALE_LATIN = re.compile(r'\s*(trillion|billion|million|thousand|tn|bn|mn|k)(?![a-z])', re.I)
_SCALE_CJK = re.compile(r'\s*(万亿|亿|万)')
_CURRENCY_CODE = re.compile(r'(?P<code>' + _CURRENCY_ALT + r')(?![a-z])', re.I)

_MONTHS = (
    ('january', 1), ('february', 2), ('march', 3), ('april', 4), ('may', 5), ('june', 6),
    ('july', 7), ('august', 8), ('september', 9), ('october', 10), ('november', 11),
    ('december', 12), ('jan', 1), ('feb', 2), ('mar', 3), ('apr', 4), ('jun', 6), ('jul', 7),
    ('aug', 8), ('sep', 9), ('sept', 9), ('oct', 10), ('nov', 11), ('dec', 12),
)
_MONTH_NUMBER = dict(_MONTHS)
_MONTH_ALT = '|'.join(sorted(_MONTH_NUMBER, key=len, reverse=True))

_ISO_DATE = re.compile(r'(?<!\d)(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})(?!\d)')
_MONTH_DAY = re.compile(
    r'(?<![a-z])(?P<month>' + _MONTH_ALT + r')\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?'
    r'(?:,?\s+(?P<y>\d{4}))?(?!\d)', re.I)
_MONTH_YEAR = re.compile(
    r'(?<![a-z])(?P<month>' + _MONTH_ALT + r')\.?,?\s+(?P<y>\d{4})(?!\d)', re.I)
_DAY_MONTH = re.compile(
    r'(?<!\d)(?P<day>\d{1,2})\s+(?P<month>' + _MONTH_ALT + r')(?![a-z])'
    r'(?:,?\s+(?P<y>\d{4}))?', re.I)

_YEAR_MONTH = re.compile(r'(?<!\d)(?P<y>\d{4})-(?P<m>0[1-9]|1[0-2])(?!\d)')
_YEAR_QUARTER = re.compile(r'(?<!\d)(?P<y>\d{4})\s*-\s*[qQ](?P<q>[1-4])(?![a-z0-9])')
_QUARTER_YEAR = re.compile(r'(?<![a-z0-9])[qQ](?P<q>[1-4])\s*[- ]\s*(?P<y>\d{4})(?!\d)')
_ORDINAL_QUARTER = re.compile(
    r'(?<!\d)(?P<n>\d{1,2})(?:st|nd|rd|th)\s+quarter(?:\s+of)?\s+(?P<y>\d{4})(?!\d)', re.I)
_YEAR_RANGE = re.compile(r'(?<!\d)(?P<a>(?:19|20)\d{2})\s*[-–—]\s*(?P<b>\d{4})(?!\d)')
_YEAR_RANGE_TO = re.compile(
    r'(?<!\d)(?P<a>(?:19|20)\d{2})\s+to\s+(?P<b>(?:19|20)\d{2})(?!\d)')
_QUARTER = re.compile(r'(?<![a-z0-9])[qQ](?P<q>[1-4])(?![a-z0-9])')
_YEAR = re.compile(r'(?<![A-Za-z0-9_])(?P<y>(?:19|20)\d{2})(?!\d)')

_ORDINAL = re.compile(r'(?<!\d)(?P<n>\d{1,3})(?:st|nd|rd|th)(?![a-z])', re.I)
# A clock time is not a ratio even though both are two numbers and a colon.
_TIME = re.compile(r'(?<!\d)(?P<h>[01]?\d|2[0-3]):(?P<m>[0-5]\d)(?!\d)')
_RATIO = re.compile(
    r'(?<!\d)(?P<l>\d{1,4})\s*(?:in|-to-|:)\s*(?P<r>\d{1,4})(?![\d.])', re.I)
_RANGE = re.compile(r'(?<!\d)(?P<a>\d{1,4})\s+to\s+(?P<b>\d{1,4})(?![\d.])', re.I)

_CITATION = re.compile(r'\[\d{1,3}\]')
_LONG_PHONE = re.compile(
    r'\+?\d{1,3}[ .-](?:\(\d{3}\)|\d{3})[ .-]\d{3}[ .-]\d{4}(?!\d)')
_US_PHONE = re.compile(r'\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)')
_LOCAL_PHONE = re.compile(r'\(?\d{3}\)?[ .-]\d{4}(?!\d)')
_LONG_DIGITS = re.compile(r'(?<!\d)\d{6,}(?!\d)')
_EMBEDDED = re.compile(r'(?<!\d)\d+(?:\.\d+)?')

DIRECTION_TERMS = (
    'increased', 'rose', 'grew', 'gained', 'surged', 'jumped', 'climbed', 'up', 'higher',
    'decreased', 'fell', 'dropped', 'declined', 'slid', 'down', 'lower',
    '增长', '上升', '增加', '上涨', '扩大', '下降', '减少', '下跌', '缩小',
)
COMPARISON_TERMS = (
    'year over year', 'year-over-year', 'yoy', 'from a year earlier', 'a year earlier',
    'month over month', 'month-over-month', 'mom', 'at a monthly rate', 'at an annual rate',
    'annual rate', 'quarter over quarter', '同比', '环比', '年化',
)
_WORD_TERMS = [(term, re.compile(r'(?<![a-z])' + re.escape(term) + r'(?![a-z])'))
               for term in DIRECTION_TERMS + COMPARISON_TERMS if term.isascii()]


def _valid_date(year, month, day):
    return 1900 <= int(year) <= 2099 and 1 <= int(month) <= 12 and 1 <= int(day) <= 31


def _temporal(kind, **parts):
    record = {'kind': kind}
    record.update(parts)
    return record


def _dates(text):
    for match in _ISO_DATE.finditer(text):
        if _valid_date(match.group('y'), match.group('m'), match.group('d')):
            yield (match.start(), match.end(), 'date', {
                'number_raw': match.group(0),
                'temporal': _temporal('day', year=int(match.group('y')),
                                      month=int(match.group('m')), day=int(match.group('d')))})
    for pattern, kind in ((_MONTH_DAY, 'day'), (_MONTH_YEAR, 'month'), (_DAY_MONTH, 'day')):
        for match in pattern.finditer(text):
            year = match.groupdict().get('y')
            month = _MONTH_NUMBER[match.group('month').lower()]
            day = match.groupdict().get('day')
            if kind == 'day' and not _valid_date(year or 2000, month, day):
                continue
            parts = {'month': month}
            if year:
                parts['year'] = int(year)
            if day and kind == 'day':
                parts['day'] = int(day)
            yield (match.start(), match.end(), 'date', {
                'number_raw': match.group(0), 'temporal': _temporal(kind, **parts)})


def _periods(text):
    for match in _YEAR_RANGE.finditer(text):
        yield (match.start(), match.end(), 'period', {
            'number_raw': match.group(0),
            'temporal': _temporal('range', start_year=int(match.group('a')),
                                  end_year=int(match.group('b')))})
    for match in _YEAR_RANGE_TO.finditer(text):
        yield (match.start(), match.end(), 'period', {
            'number_raw': match.group(0),
            'temporal': _temporal('range', start_year=int(match.group('a')),
                                  end_year=int(match.group('b')))})
    for match in _YEAR_MONTH.finditer(text):
        yield (match.start(), match.end(), 'period', {
            'number_raw': match.group(0),
            'temporal': _temporal('month', year=int(match.group('y')),
                                  month=int(match.group('m')))})
    for pattern, kind in ((_YEAR_QUARTER, 'quarter'), (_QUARTER_YEAR, 'quarter')):
        for match in pattern.finditer(text):
            yield (match.start(), match.end(), 'period', {
                'number_raw': match.group(0),
                'temporal': _temporal(kind, year=int(match.group('y')),
                                      quarter=int(match.group('q')))})
    for match in _ORDINAL_QUARTER.finditer(text):
        yield (match.start(), match.end(), 'period', {
            'number_raw': match.group(0),
            'temporal': _temporal('quarter', year=int(match.group('y')),
                                  quarter=int(match.group('n')))})
    for match in _QUARTER.finditer(text):
        yield (match.start(), match.end(), 'period', {
            'number_raw': match.group(0),
            'temporal': _temporal('quarter', quarter=int(match.group('q')))})
    for match in _YEAR.finditer(text):
        yield (match.start(), match.end(), 'period', {
            'number_raw': match.group(0),
            'temporal': _temporal('year', year=int(match.group('y')))})


def _identifiers(text):
    for match in _CITATION.finditer(text):
        yield (match.start(), match.end(), 'identifier', {
            'number_raw': match.group(0), 'digits': match.group(0).strip('[]'),
            'identifier': 'citation'})
    for pattern, kind in ((_LONG_PHONE, 'phone'), (_US_PHONE, 'phone'), (_LOCAL_PHONE, 'phone')):
        for match in pattern.finditer(text):
            if sum(ch.isdigit() for ch in match.group(0)) < 7:
                continue
            yield (match.start(), match.end(), 'identifier', {
                'number_raw': match.group(0),
                'digits': ''.join(ch for ch in match.group(0) if ch.isdigit()),
                'identifier': kind})
    for match in _LONG_DIGITS.finditer(text):
        yield (match.start(), match.end(), 'identifier', {
            'number_raw': match.group(0), 'digits': match.group(0), 'identifier': 'digit_run'})


def _times(text):
    for match in _TIME.finditer(text):
        yield (match.start(), match.end(), 'time', {
            'number_raw': match.group(0),
            'temporal': _temporal('time', hour=int(match.group('h')),
                                  minute=int(match.group('m')))})


def _ratios(text):
    for match in _RATIO.finditer(text):
        yield (match.start(), match.end(), 'ratio', {
            'number_raw': match.group(0),
            'ratio': {'left': int(match.group('l')), 'right': int(match.group('r'))}})


def _ranges(text):
    for match in _RANGE.finditer(text):
        yield (match.start(), match.end(), 'range', {
            'number_raw': match.group(0),
            'range': {'start': int(match.group('a')), 'end': int(match.group('b'))}})


def _ordinals(text):
    for match in _ORDINAL.finditer(text):
        yield (match.start(), match.end(), 'ordinal', {
            'number_raw': match.group(0), 'value': int(match.group('n'))})


def _tail_parts(text, end):
    """(scale_factor, scale_name, unit, width) for what follows the number at `end`."""
    tail = text[end:end + 80]
    factor, scale, used = 1.0, '', 0
    match = _SCALE_LATIN.match(tail) or _SCALE_CJK.match(tail)
    if match:
        word = match.group(1).lower()
        factor = _SCALE_FACTOR[word]
        # 亿 and 万 have no English name in units.SCALE_NAMES; the scale keeps the word
        # that was written rather than becoming an empty string with a factor behind it.
        scale = units.scale_name(factor) or word
        used = match.end()
    rest = tail[used:]
    unit, extra = '', 0
    percent = units.PERCENT_AFTER.match(rest)
    if percent:
        token = percent.group(1).lower()
        unit = units.PERCENT_POINT if token in units.POINT_WORDS else units.PERCENT
        extra = percent.end()
    else:
        for pattern, name in units.UNIT_WORDS:
            unit_match = pattern.match(rest)
            if unit_match:
                unit, extra = name, unit_match.end()
                break
        else:
            offset = len(rest) - len(rest.lstrip(' \t'))
            code = _CURRENCY_CODE.match(rest, offset)
            if code:
                unit, extra = code.group('code').upper(), code.end()
    return factor, scale, unit, used + extra


def _numbers(text):
    for match in _NUMBER_EXPR.finditer(text):
        start, end = match.start(), match.end()
        factor, scale, unit, width = _tail_parts(text, end)
        end += width
        prefix = ''
        if match.group('sign1'):
            prefix = units.CURRENCY_SIGNS[match.group('sign1')]
        elif match.group('code1'):
            prefix = match.group('code1').upper()
        flags = []
        currency = prefix
        if unit in units.CURRENCIES:
            if currency and unit != currency:
                flags.append('currency_conflict')
            else:
                currency = unit
            unit = currency
        elif currency and not unit:
            unit = currency
        if start > 0 and text[start - 1] == '(' and end < len(text) and text[end] == ')':
            flags.append('parenthesized')
        category = ('percent' if unit == units.PERCENT else
                    'percentage_point' if unit == units.PERCENT_POINT else
                    'money' if currency else
                    'quantity' if unit else
                    'magnitude' if scale else 'bare')
        yield (start, end, category, {
            'number_raw': match.group('num'),
            'value': units.parse_number(match.group('num')),
            'scale': scale, 'scale_factor': factor,
            'unit': unit, 'unit_family': units.unit_family(unit) if unit else 'unknown',
            'currency': currency, 'flags': flags})


def _embedded(text):
    for match in _EMBEDDED.finditer(text):
        yield (match.start(), match.end(), 'embedded', {
            'number_raw': match.group(0),
            'digits': ''.join(ch for ch in match.group(0) if ch.isdigit())})


# Leftmost-longest; on equal length the earlier entry wins. Dates outrank a bare year, a
# period outranks a day number, an identifier outranks its digits, and every specific class
# outranks `embedded`.
_MATCHERS = (
    ('date', _dates), ('period', _periods), ('identifier', _identifiers),
    ('time', _times), ('ratio', _ratios), ('range', _ranges), ('ordinal', _ordinals),
    ('number', _numbers), ('embedded', _embedded),
)


def _scan(text):
    found = []
    for priority, (_name, matcher) in enumerate(_MATCHERS):
        for start, end, category, payload in matcher(text):
            found.append((start, end, priority, category, payload))
    found.sort(key=lambda item: (item[0], -(item[1] - item[0]), item[2]))
    accepted, last_end = [], -1
    for start, end, _priority, category, payload in found:
        if start < last_end:
            continue
        accepted.append((start, end, category, payload))
        last_end = end
    return accepted


def _cues(text, sentence_start, sentence_end):
    """Lexical terms near the candidate. N1 records them; N3 decides what they mean."""
    window, cues = text[sentence_start:sentence_end], []
    for term, pattern in _WORD_TERMS:
        for match in pattern.finditer(window):
            cues.append({'term': term, 'role': _role(term),
                         'start': sentence_start + match.start(),
                         'length': match.end() - match.start()})
    for term in DIRECTION_TERMS + COMPARISON_TERMS:
        if term.isascii():
            continue
        index = window.find(term)
        while index >= 0:
            cues.append({'term': term, 'role': _role(term),
                         'start': sentence_start + index, 'length': len(term)})
            index = window.find(term, index + 1)
    cues.sort(key=lambda cue: cue['start'])
    return cues


def _role(term):
    return 'direction' if term in DIRECTION_TERMS else 'comparison'


def _record(article, field_name, start, end, category, payload):
    field = article.field(field_name)
    raw_start, raw_end = field.raw_span(start, end)
    number_raw = payload.get('number_raw', '')
    sentence_index = article.sentence_of(field_name, start)
    sentence = next((s for s in article.sentences if s['index'] == sentence_index), None)
    sentence_start = sentence['start'] if sentence else 0
    sentence_end = sentence['end'] if sentence else len(field.text)
    record = {
        'id': '', 'field': field_name, 'start': start, 'end': end, 'length': end - start,
        'global_start': field.global_start + start, 'global_end': field.global_start + end,
        'raw_start': raw_start, 'raw_end': raw_end,
        'raw': field.text[start:end], 'category': category,
        'sentence': sentence_index,
        'segment': article.segment_of(field_name, start),
        'context': field.text[max(0, start - 60):end + 60],
        'cues': _cues(field.text, sentence_start, sentence_end),
        'status': 'candidate',
    }
    record.update({'number_raw': number_raw})
    for key in ('value', 'scale', 'scale_factor', 'unit', 'unit_family', 'currency',
                'flags', 'temporal', 'ratio', 'range', 'digits', 'identifier'):
        if key in payload:
            record[key] = payload[key]
    record.setdefault('value', None)
    record.setdefault('temporal', None)
    record.setdefault('ratio', None)
    record.setdefault('range', None)
    record.setdefault('flags', [])
    record.setdefault('scale', '')
    record.setdefault('scale_factor', 1.0)
    record.setdefault('unit', '')
    record.setdefault('unit_family', 'unknown')
    record.setdefault('currency', '')
    return record


def _coverage(article, candidates):
    """Digit positions per field that no candidate covers. Should always be empty."""
    spans = {}
    for candidate in candidates:
        spans.setdefault(candidate['field'], []).append((candidate['start'], candidate['end']))
    total = covered = 0
    uncovered = []
    for name, field in article.fields.items():
        ranges = spans.get(name, [])
        for index, char in enumerate(field.text):
            # `\d` is Unicode decimal digits; '²' in 'm²' is a unit exponent, not a number
            # token, and `str.isdigit()` would count it and report a false gap.
            if not char.isdecimal():
                continue
            total += 1
            if any(start <= index < end for start, end in ranges):
                covered += 1
            else:
                uncovered.append({'field': name, 'index': index, 'char': char})
    return {'digits': total, 'covered': covered, 'uncovered': uncovered}


def extract(article):
    """N1's output for one N0 article. Deterministic for a given text."""
    if article is None or not getattr(article, 'fields', None):
        raise ValueError('N1 needs an ArticleText built by N0')
    candidates = []
    for name in ('title', 'summary'):
        field = article.fields.get(name)
        if field is None:
            continue
        for start, end, category, payload in _scan(field.text):
            candidates.append(_record(article, name, start, end, category, payload))
    candidates.sort(key=lambda item: (0 if item['field'] == 'title' else 1, item['start']))
    for index, candidate in enumerate(candidates, 1):
        candidate['id'] = f'c{index:04d}'
    by_category, by_field = {}, {}
    for candidate in candidates:
        by_category[candidate['category']] = by_category.get(candidate['category'], 0) + 1
        by_field[candidate['field']] = by_field.get(candidate['field'], 0) + 1
    coverage = _coverage(article, candidates)
    return {
        'version': VERSION, 'source_hash': article.source_hash,
        'text_hash': article.text_hash, 'candidates': candidates,
        'stats': {'total': len(candidates), 'by_category': by_category,
                  'by_field': by_field, 'coverage': coverage},
    }
