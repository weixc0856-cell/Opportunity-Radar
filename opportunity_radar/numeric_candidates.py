"""N1: numeric candidate extraction over the full N0 text.

N1 is deterministic and deliberately shallow. It does not decide what a number means, who it
belongs to, whether it is a level or a change, or whether it is commercially interesting -
those are N2 and N3's questions. It finds numeric expressions (atoms), says what lexical
class each one looks like, records where it came from, and records the relations the text
states between atoms (ranges, from/to, direction cues, comparison cues).

Two rules shape the implementation:

1. Nothing disappears. Every decimal digit in the article belongs to exactly one atom. A
   digit inside a word or a URL still becomes an atom, classed `unclassified_numeric`, so a
   later node has to make an explicit decision instead of the digit silently vanishing. (A
   superscript like the 2 in 'm²' is a unit exponent, not a digit in this sense.)
2. Nothing is computed into a final value. `$92.8 billion` becomes value 92.8 with scale
   billion, not 92800000000; a percentage point stays distinct from a percent. Scale, unit,
   currency and value normalisation are N4's job, and N1 must not pre-empt it with a value a
   later node cannot audit.

Atoms and relations are separate layers. A range or a from/to statement does not replace the
atoms it mentions; the expression group references their candidate IDs. The scan is
leftmost-longest: at any position the longest atom wins, and an atom that overlaps an
accepted one is dropped.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from . import units

VERSION = 'n1-v1'
# The source hash is recorded with every run so a rule change cannot reuse a
# result produced by different rules under the same node version.
RULESET = hashlib.sha256(Path(__file__).resolve().read_bytes()).hexdigest()[:16]

_CURRENCY_ALT = '|'.join(sorted((code.lower() for code in units.CURRENCIES),
                                key=len, reverse=True))
_SCALE_FACTOR = dict(units.SCALES)

# A number, optionally preceded by a currency sign or code. The lookbehind keeps the scanner
# out of the middle of an ASCII alphanumeric token; `unclassified` below catches what that
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
_DURATION = re.compile(r'\s*(months?|weeks?|days?|years?|hours?|minutes?|quarters?)(?![a-z])',
                       re.I)
_DURATION_UNITS = {'month', 'months', 'week', 'weeks', 'day', 'days', 'year', 'years',
                   'hour', 'hours', 'minute', 'minutes', 'quarter', 'quarters'}
# Nouns a scaled count usually carries. A number followed by one of these is a quantity with
# that noun as its unit; anything else after a scale stays a magnitude and N2/N4 decide.
_COUNT_NOUNS = re.compile(
    r'\s*(vehicles?|customers?|users?|employees?|people|persons?|compan(?:y|ies)|homes?|'
    r'stores?|units?|jobs?|patients?|subscribers?|members?|devices?|sites?|machines?|'
    r'shipments?|orders?|accounts?|passengers?|schools?|hospitals?|households?)(?![a-z])', re.I)
_COUNT_UNITS = {'vehicle', 'vehicles', 'customer', 'customers', 'user', 'users', 'employee',
                'employees', 'people', 'person', 'persons', 'company', 'companies', 'home',
                'homes', 'store', 'stores', 'unit', 'units', 'job', 'jobs', 'patient',
                'patients', 'subscriber', 'subscribers', 'member', 'members', 'device',
                'devices', 'site', 'sites', 'machine', 'machines', 'shipment', 'shipments',
                'order', 'orders', 'account', 'accounts', 'passenger', 'passengers', 'school',
                'schools', 'hospital', 'hospitals', 'household', 'households'}
_CURRENCY_WORDS = re.compile(
    r'\s*(dollars?|euros?|pounds?|yen|yuan|renminbi|rupees?)(?![a-z])', re.I)
_CURRENCY_WORD_CODES = {
    'dollar': 'USD', 'dollars': 'USD', 'euro': 'EUR', 'euros': 'EUR', 'pound': 'GBP',
    'pounds': 'GBP', 'yen': 'JPY', 'yuan': 'CNY', 'renminbi': 'CNY', 'rupee': 'INR',
    'rupees': 'INR',
}

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
_FISCAL_YEAR = re.compile(r'(?<![a-z])fy\s?(?P<y>(?:19|20)\d{2})(?!\d)', re.I)
_QUARTER = re.compile(r'(?<![a-z0-9])[qQ](?P<q>[1-4])(?![a-z0-9])')
_YEAR = re.compile(r'(?<![A-Za-z0-9_])(?P<y>(?:19|20)\d{2})(?!\d)')

_ORDINAL = re.compile(r'(?<!\d)(?P<n>\d{1,3})(?:st|nd|rd|th)(?![a-z])', re.I)
# A clock time is not a ratio even though both are two numbers and a colon.
_TIME = re.compile(r'(?<!\d)(?P<h>[01]?\d|2[0-3]):(?P<m>[0-5]\d)(?!\d)')
_RATIO = re.compile(
    r'(?<!\d)(?P<l>\d{1,4})\s*(?:in|per|-to-|:)\s*(?P<r>\d{1,4})(?![\d.])', re.I)
_SCIENTIFIC = re.compile(
    r'(?<![A-Za-z0-9_.])[-+]?\d+(?:\.\d+)?[eE][-+]?\d+(?![A-Za-z0-9_])')

_CITATION = re.compile(r'\[\d{1,3}\]')
_FORM = re.compile(r'(?<![a-z0-9])(?:form\s+)?\d{1,2}-k(?![a-z0-9])', re.I)
_LONG_PHONE = re.compile(
    r'\+?\d{1,3}[ .-](?:\(\d{3}\)|\d{3})[ .-]\d{3}[ .-]\d{4}(?!\d)')
_US_PHONE = re.compile(r'\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)')
_LOCAL_PHONE = re.compile(r'\(?\d{3}\)?[ .-]\d{4}(?!\d)')
_LONG_DIGITS = re.compile(r'(?<!\d)\d{6,}(?!\d)')
_EMBEDDED = re.compile(r'(?<!\d)\d+(?:\.\d+)?')

DIRECTION_TERMS = (
    'increased', 'increase', 'rose', 'rise', 'grew', 'grow', 'gained', 'gain', 'surged',
    'jumped', 'climbed', 'up', 'higher', 'decreased', 'decrease', 'fell', 'fall', 'dropped',
    'drop', 'declined', 'decline', 'slid', 'down', 'lower',
    '增长', '上升', '增加', '上涨', '扩大', '下降', '减少', '下跌', '缩小',
)
TEMPORAL_TERMS = (
    'year over year', 'year-over-year', 'year-on-year', 'yoy', 'month over month',
    'month-over-month', 'month-on-month', 'mom', 'quarter over quarter',
    'quarter-over-quarter', 'qoq', 'over the past', 'in the past', '同比', '环比', '年化',
)
COMPARISON_TERMS = (
    'compared with', 'compared to', 'versus', 'vs.', 'than', 'from a year earlier',
    'from a year ago', 'a year earlier', 'year earlier', 'prior year', 'previous year',
    # The BEA releases state a change "at a monthly rate"; that is a comparison basis, and
    # dropping the cue would put the number back where R2 Batch 6 found the model stuck.
    'at a monthly rate', 'at an annual rate', 'monthly rate', 'quarterly rate', 'annual rate',
)


def _terms_pattern(terms):
    """One regex for a term list: word-bounded for ASCII, literal for CJK."""
    parts = []
    for term in sorted(terms, key=len, reverse=True):
        if term.isascii():
            parts.append(r'(?<![a-z])' + re.escape(term) + r'(?![a-z])')
        else:
            parts.append(re.escape(term))
    return re.compile('|'.join(parts), re.I)


_DIRECTION = _terms_pattern(DIRECTION_TERMS)
_TEMPORAL = _terms_pattern(TEMPORAL_TERMS)
_COMPARISON = _terms_pattern(COMPARISON_TERMS)


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
    for pattern in (_YEAR_QUARTER, _QUARTER_YEAR):
        for match in pattern.finditer(text):
            yield (match.start(), match.end(), 'period', {
                'number_raw': match.group(0),
                'temporal': _temporal('quarter', year=int(match.group('y')),
                                      quarter=int(match.group('q')))})
    for match in _ORDINAL_QUARTER.finditer(text):
        yield (match.start(), match.end(), 'period', {
            'number_raw': match.group(0),
            'temporal': _temporal('quarter', year=int(match.group('y')),
                                  quarter=int(match.group('n')))})
    for match in _FISCAL_YEAR.finditer(text):
        yield (match.start(), match.end(), 'period', {
            'number_raw': match.group(0),
            'temporal': _temporal('fiscal_year', year=int(match.group('y')))})
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
    for match in _FORM.finditer(text):
        yield (match.start(), match.end(), 'identifier', {
            'number_raw': match.group(0),
            'digits': ''.join(ch for ch in match.group(0) if ch.isdigit()),
            'identifier': 'form'})
    for pattern in (_LONG_PHONE, _US_PHONE, _LOCAL_PHONE):
        for match in pattern.finditer(text):
            if sum(ch.isdigit() for ch in match.group(0)) < 7:
                continue
            yield (match.start(), match.end(), 'identifier', {
                'number_raw': match.group(0),
                'digits': ''.join(ch for ch in match.group(0) if ch.isdigit()),
                'identifier': 'phone'})
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


def _ordinals(text):
    for match in _ORDINAL.finditer(text):
        yield (match.start(), match.end(), 'ordinal', {
            'number_raw': match.group(0), 'value': int(match.group('n'))})


def _scientific(text):
    for match in _SCIENTIFIC.finditer(text):
        yield (match.start(), match.end(), 'scalar', {
            'number_raw': match.group(0), 'value': float(match.group(0)),
            'flags': ['scientific']})


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
            duration = _DURATION.match(rest)
            count = _COUNT_NOUNS.match(rest)
            word = _CURRENCY_WORDS.match(rest)
            if duration:
                unit, extra = duration.group(1).lower(), duration.end()
            elif count:
                unit, extra = count.group(1).lower(), count.end()
            elif word:
                unit = _CURRENCY_WORD_CODES[word.group(1).lower()]
                extra = word.end()
            else:
                offset = len(rest) - len(rest.lstrip(' \t'))
                code = _CURRENCY_CODE.match(rest, offset)
                if code:
                    unit, extra = code.group('code').upper(), code.end()
    return factor, scale, unit, used + extra


def _unit_family(unit):
    if unit in _DURATION_UNITS:
        return 'duration'
    if unit in _COUNT_UNITS:
        return 'count'
    return units.unit_family(unit) if unit else 'unknown'


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
        candidate_type = ('percentage' if unit == units.PERCENT else
                          'percentage_point' if unit == units.PERCENT_POINT else
                          'currency' if currency else
                          'quantity' if unit else
                          'magnitude' if scale else 'scalar')
        yield (start, end, candidate_type, {
            'number_raw': match.group('num'),
            'value': units.parse_number(match.group('num')),
            'scale': scale, 'scale_factor': factor,
            'unit': unit, 'unit_family': _unit_family(unit),
            'currency': currency, 'flags': flags})


def _unclassified(text):
    for match in _EMBEDDED.finditer(text):
        yield (match.start(), match.end(), 'unclassified_numeric', {
            'number_raw': match.group(0),
            'digits': ''.join(ch for ch in match.group(0) if ch.isdecimal())})


# Leftmost-longest; on equal length the earlier entry wins. Dates outrank a bare year, a
# period outranks a day number, an identifier outranks its digits, and every specific class
# outranks `unclassified_numeric`.
_MATCHERS = (
    ('date', _dates), ('period', _periods), ('identifier', _identifiers),
    ('time', _times), ('ratio', _ratios), ('scientific', _scientific),
    ('ordinal', _ordinals), ('number', _numbers), ('unclassified', _unclassified),
)


def _scan(text):
    found = []
    for priority, (_name, matcher) in enumerate(_MATCHERS):
        for start, end, candidate_type, payload in matcher(text):
            found.append((start, end, priority, candidate_type, payload))
    found.sort(key=lambda item: (item[0], -(item[1] - item[0]), item[2]))
    accepted, last_end = [], -1
    for start, end, _priority, candidate_type, payload in found:
        if start < last_end:
            continue
        accepted.append((start, end, candidate_type, payload))
        last_end = end
    return accepted


def _cues(text, sentence_start, sentence_end, base=0):
    """Lexical terms in the sentence. N1 records them; N3 decides what they mean."""
    window, cues = text[sentence_start:sentence_end], []
    for pattern, role, terms in ((_DIRECTION, 'direction', DIRECTION_TERMS),
                                 (_TEMPORAL, 'comparison', TEMPORAL_TERMS),
                                 (_COMPARISON, 'comparison', COMPARISON_TERMS)):
        for match in pattern.finditer(window):
            term = match.group(0).lower()
            if term not in terms:
                continue
            cues.append({'term': term, 'role': role,
                         'start': base + sentence_start + match.start(),
                         'length': match.end() - match.start()})
    cues.sort(key=lambda cue: cue['start'])
    return cues


def _status(candidate_type, flags):
    if candidate_type == 'unclassified_numeric':
        return 'unclassified'
    if {'parenthesized', 'currency_conflict'} & set(flags or ()):
        return 'ambiguous'
    return 'detected'


def _record(article, field_name, start, end, candidate_type, payload):
    field = article.field(field_name)
    raw_start, raw_end = field.raw_span(start, end)
    sentence_index = article.sentence_of(field_name, start)
    sentence = article.sentences[sentence_index] if sentence_index is not None else None
    paragraph_index = article.paragraph_of(field_name, start)
    paragraph = article.paragraphs[paragraph_index] if paragraph_index is not None else None
    sentence_start = sentence['field_start'] if sentence else 0
    sentence_end = sentence['field_end'] if sentence else len(field.text)
    flags = list(payload.get('flags') or [])
    record = {
        'candidate_id': '',
        'candidate_type': candidate_type,
        'raw_text': field.text[start:end],
        'field': field_name,
        # `start`/`end` are positions in the N0 document text, which is what the contract
        # promises. `field_start`/`field_end` are the same span inside the title or body
        # field, which is what the field text can be sliced with.
        'start': field.global_start + start, 'end': field.global_start + end,
        'field_start': start, 'field_end': end,
        'length': end - start,
        'global_start': field.global_start + start, 'global_end': field.global_start + end,
        'raw_start': raw_start, 'raw_end': raw_end,
        'sentence': sentence_index,
        'sentence_id': sentence['sentence_id'] if sentence else None,
        'paragraph': paragraph_index,
        'paragraph_id': paragraph['paragraph_id'] if paragraph else None,
        'context': sentence['text'] if sentence else field.text[start:end],
        'context_start': field.global_start + sentence_start,
        'context_end': field.global_start + sentence_end,
        'cues': _cues(field.text, sentence_start, sentence_end, field.global_start),
        'detection_method': 'regex',
        'detection_status': _status(candidate_type, flags),
        'related_candidates': [],
        'status': 'candidate',
    }
    record['number_raw'] = payload.get('number_raw', '')
    for key in ('value', 'scale', 'scale_factor', 'unit', 'unit_family', 'currency',
                'flags', 'temporal', 'ratio', 'digits', 'identifier'):
        if key in payload:
            record[key] = payload[key]
    record.setdefault('value', None)
    record.setdefault('temporal', None)
    record.setdefault('ratio', None)
    record.setdefault('flags', [])
    record.setdefault('scale', '')
    record.setdefault('scale_factor', 1.0)
    record.setdefault('unit', '')
    record.setdefault('unit_family', 'unknown')
    record.setdefault('currency', '')
    return record


def _group(expression_type, raw_text, start, end, candidate_ids, sentence, base):
    return {
        'expression_id': '',
        'expression_type': expression_type,
        'raw_text': raw_text,
        'start': base + start, 'end': base + end,
        'candidate_ids': [candidate['candidate_id'] for candidate in candidate_ids],
        'sentence_id': sentence['sentence_id'] if sentence else None,
        'paragraph_id': sentence['paragraph_id'] if sentence else None,
        'detection_method': 'custom_rule',
        'detection_status': 'detected',
    }


def _from_start(text, atom):
    window_start = max(0, atom['field_start'] - 12)
    index = text.rfind('from', window_start, atom['field_start'])
    return index if index >= 0 else atom['field_start']


def _pair_groups(text, atoms, sentence, base):
    groups = []
    for first, second in zip(atoms, atoms[1:]):
        gap = text[first['field_end']:second['field_start']]
        if re.fullmatch(r'\s*[–—]\s*', gap) or re.fullmatch(r'\s*-\s*', gap):
            groups.append(_group('range', text[first['field_start']:second['field_end']],
                                 first['field_start'], second['field_end'], [first, second],
                                 sentence, base))
        elif re.fullmatch(r'\s+to\s+', gap, re.I):
            start = _from_start(text, first)
            groups.append(_group('from_to', text[start:second['field_end']], start,
                                 second['field_end'], [first, second], sentence, base))
        elif re.fullmatch(r'\s+from\s+', gap, re.I):
            before = text[max(0, first['field_start'] - 12):first['field_start']].lower()
            if 'to' in before:
                groups.append(_group('from_to', text[first['field_start']:second['field_end']],
                                     first['field_start'], second['field_end'], [first, second],
                                     sentence, base))
    return groups


def _cue_groups(text, atoms, sentence, base):
    """Direction, comparison and temporal relations stated near the atoms."""
    groups, sentence_text = [], sentence['text']
    offset = sentence['field_start']
    for match in _DIRECTION.finditer(sentence_text):
        cue_start, cue_end = offset + match.start(), offset + match.end()
        following = [atom for atom in atoms
                     if cue_end <= atom['field_start'] <= cue_end + 40]
        if following:
            atom = following[0]
            groups.append(_group('increase_decrease', text[cue_start:atom['field_end']],
                                 cue_start, atom['field_end'], [atom], sentence, base))
    for atom in atoms:
        tail = text[atom['field_end']:min(sentence['field_end'], atom['field_end'] + 20)]
        match = _DIRECTION.search(tail)
        if match and not any(atom['field_end'] < other['field_start']
                             < atom['field_end'] + match.start() for other in atoms):
            groups.append(_group('increase_decrease',
                                 text[atom['field_start']:atom['field_end'] + match.end()],
                                 atom['field_start'], atom['field_end'] + match.end(),
                                 [atom], sentence, base))
    for match in _TEMPORAL.finditer(sentence_text):
        start, end = offset + match.start(), offset + match.end()
        after = [atom for atom in atoms if end <= atom['field_start'] <= end + 30]
        before = [atom for atom in atoms
                  if atom['field_end'] <= start and start - atom['field_end'] <= 60]
        near = before + after
        if after:
            end = after[-1]['field_end']
        groups.append(_group('temporal_comparison', text[start:end], start, end,
                             near, sentence, base))
    for match in _COMPARISON.finditer(sentence_text):
        start, end = offset + match.start(), offset + match.end()
        after = [atom for atom in atoms if end <= atom['field_start'] <= end + 60]
        before = [atom for atom in atoms
                  if atom['field_end'] <= start and start - atom['field_end'] <= 60]
        atom = (after or before or [None])[0]
        if atom is None:
            groups.append(_group('comparison', text[start:end], start, end, [], sentence, base))
            continue
        group_start = min(start, atom['field_start'])
        group_end = max(end, atom['field_end'])
        groups.append(_group('comparison', text[group_start:group_end], group_start, group_end,
                             [atom], sentence, base))
    return groups


def _expression_groups(article, candidates):
    by_sentence = {}
    for candidate in candidates:
        by_sentence.setdefault((candidate['field'], candidate['sentence']), []).append(candidate)
    # A temporal comparison can be stated without a number ('year over year'), so every
    # sentence is considered, not only the ones that already contain an atom.
    for sentence in article.sentences:
        by_sentence.setdefault((sentence['field'], sentence['index']), [])
    groups, seen = [], set()
    for (field_name, sentence_index), atoms in sorted(
            by_sentence.items(), key=lambda item: (item[0][0], item[0][1] or 0)):
        if sentence_index is None:
            continue
        sentence = article.sentences[sentence_index]
        field = article.field(field_name)
        atoms = sorted(atoms, key=lambda atom: atom['field_start'])
        found = (_pair_groups(field.text, atoms, sentence, field.global_start)
                 + _cue_groups(field.text, atoms, sentence, field.global_start))
        for group in found:
            key = (group['expression_type'], group['start'], group['end'],
                   tuple(group['candidate_ids']))
            if key in seen:
                continue
            seen.add(key)
            groups.append(group)
    groups.sort(key=lambda group: (group['start'], group['expression_type']))
    for group in groups:
        material = '\x00'.join((article.content_hash, VERSION, group['expression_type'],
                                str(group['start']), str(group['end']),
                                ','.join(group['candidate_ids'])))
        group['expression_id'] = 'g' + hashlib.sha256(
            material.encode('utf-8')).hexdigest()[:16]
    related = {}
    for group in groups:
        for candidate_id in group['candidate_ids']:
            related.setdefault(candidate_id, set()).update(
                other for other in group['candidate_ids'] if other != candidate_id)
    for candidate in candidates:
        candidate['related_candidates'] = sorted(related.get(candidate['candidate_id'], ()))
    return groups


def _coverage(article, candidates):
    """Digit positions per field that no candidate covers. Should always be empty."""
    spans = {}
    for candidate in candidates:
        spans.setdefault(candidate['field'], []).append(
            (candidate['field_start'], candidate['field_end']))
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
    for name in ('title', 'body'):
        field = article.fields.get(name)
        if field is None:
            continue
        for start, end, candidate_type, payload in _scan(field.text):
            candidates.append(_record(article, name, start, end, candidate_type, payload))
    candidates.sort(key=lambda item: (0 if item['field'] == 'title' else 1,
                                      item['field_start']))
    for candidate in candidates:
        material = '\x00'.join((article.content_hash, VERSION, candidate['candidate_type'],
                                str(candidate['start']), candidate['raw_text']))
        candidate['candidate_id'] = 'c' + hashlib.sha256(
            material.encode('utf-8')).hexdigest()[:16]
    groups = _expression_groups(article, candidates)
    by_type = {}
    for candidate in candidates:
        by_type[candidate['candidate_type']] = by_type.get(candidate['candidate_type'], 0) + 1
    for group in groups:
        candidate_ids = {candidate['candidate_id'] for candidate in candidates}
        missing = [value for value in group['candidate_ids'] if value not in candidate_ids]
        if missing:
            raise ValueError(f'expression group references unknown candidates: {missing}')
    statistics = {
        'candidate_count': len(candidates),
        'expression_group_count': len(groups),
        'unclassified_numeric_count': by_type.get('unclassified_numeric', 0),
        'by_type': by_type,
        'coverage': _coverage(article, candidates),
    }
    return {
        'document_id': article.document_id,
        'content_hash': article.content_hash,
        'text_hash': article.text_hash,
        'extractor_version': VERSION,
        'ruleset': RULESET,
        'candidates': candidates,
        'expression_groups': groups,
        'statistics': statistics,
    }
