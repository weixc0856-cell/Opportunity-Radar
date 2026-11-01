"""SEC EDGAR companyconcept client and normaliser — independent channel.

Scope (G-D2): the ten companies in docs/SEC_SAMPLE_MATRIX_2026-11-01.md and the tags in
labels.py. Custom taxonomies, dimensional facts and anything not mapped are marked, not guessed.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass

from . import http
from .http import IngestError

AMENDMENT = 'amendment'
ORIGINAL = 'original'
SUBSEQUENT_COMPARATIVE = 'subsequent_comparative'
UNKNOWN = 'unknown'

CURRENT = 'current_selected'
SUPERSEDED = 'superseded'
UNRESOLVED = 'unresolved'


@dataclass(frozen=True)
class ConceptRequest:
    cik: str
    taxonomy: str
    tag: str
    metric_id: str

    @property
    def path(self):
        return f'/api/xbrl/companyconcept/CIK{self.cik.zfill(10)}/{self.taxonomy}/{self.tag}.json'


def filing_relation(form):
    """Provisional value for a single row.

    Only a /A form is self-evident. Everything else stays UNKNOWN here and is decided in
    batch by assign_filing_relations(), which can see the other accessions for the period.
    """
    form = (form or '').strip().upper()
    if form.endswith('/A'):
        return AMENDMENT
    return UNKNOWN


def assign_filing_relations(facts):
    """Classify every fact in a batch: original / amendment / subsequent_comparative / unknown.

    - amendment: the form is a /A.
    - original: the earliest filed accession for this (entity, tag, unit, period).
    - subsequent_comparative: a later accession re-reports a period already reported.
    - unknown: no usable filed date; we do not fall back to ORIGINAL.
    Mutates the facts in place and returns a count per class.
    """
    groups = defaultdict(list)
    for fact in facts:
        groups[(fact['cik'], fact['taxonomy'], fact['tag'], fact['unit'],
                fact['period_start'], fact['period_end'])].append(fact)
    counts = {ORIGINAL: 0, AMENDMENT: 0, SUBSEQUENT_COMPARATIVE: 0, UNKNOWN: 0}
    for items in groups.values():
        dated = [f for f in items if f.get('filed')]
        earliest = min(dated, key=lambda f: (f['filed'], f['accn'])) if dated else None
        for fact in items:
            if (fact.get('form') or '').strip().upper().endswith('/A'):
                relation = AMENDMENT
            elif not fact.get('filed'):
                relation = UNKNOWN
            elif fact is earliest:
                relation = ORIGINAL
            else:
                relation = SUBSEQUENT_COMPARATIVE
            fact['filing_relation'] = relation
            counts[relation] += 1
    return counts


class SecClient:
    def __init__(self, settings, transport=None, limiter=None, sleep=None):
        self.settings = settings
        self.transport = transport or http.UrllibTransport()
        self.limiter = limiter
        self._get_kwargs = {} if sleep is None else {'sleep': sleep}
        self.requests = 0

    def _headers(self):
        return {'User-Agent': self.settings.sec_user_agent, 'Accept-Encoding': 'gzip, deflate',
                'Accept': 'application/json'}

    def companyconcept(self, request, store=None):
        url = self.settings.sec_base_url + request.path
        payload = http.get_json(self.transport, url, headers=self._headers(),
                                timeout=self.settings.timeout, limiter=self.limiter,
                                **self._get_kwargs)
        self.requests += 1
        if store is not None:
            body = __import__('json').dumps(payload, ensure_ascii=False).encode('utf-8')
            store.save_snapshot('sec-edgar', url, f'{request.cik}|{request.taxonomy}|{request.tag}',
                                200, body)
        return payload


def normalize_concept(payload, request, snapshot_hash, seen_at):
    """Return (facts, flag). An empty units map is `no_facts`, never a zero-valued fact."""
    if not isinstance(payload, dict):
        raise IngestError(http.SCHEMA, 'concept payload is not an object')
    units = payload.get('units')
    if units is None:
        raise IngestError(http.SCHEMA, 'concept payload has no units')
    if not isinstance(units, dict):
        raise IngestError(http.SCHEMA,
                          f'concept units is {type(units).__name__}, expected an object')
    if not units:
        return [], 'no_facts'
    cik = str(payload.get('cik') or request.cik).zfill(10)
    if cik != request.cik.zfill(10):
        raise IngestError(http.SCHEMA, f'cik mismatch: payload {cik}, requested {request.cik}')
    facts = []
    for unit, rows in units.items():
        if not isinstance(rows, list):
            raise IngestError(http.SCHEMA, f'units[{unit!r}] is not a list')
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise IngestError(http.SCHEMA, f'units[{unit!r}][{index}] is not an object')
            accn = str(row.get('accn') or '').strip()
            if not accn:
                raise IngestError(http.SCHEMA, f'units[{unit!r}][{index}] has no accession')
            val = row.get('val')
            flags = []
            if val is None:
                value = None
                flags.append('missing_value')
            elif isinstance(val, bool) or not isinstance(val, (int, float)):
                raise IngestError(http.SCHEMA,
                                  f'units[{unit!r}][{index}] val is not numeric: {val!r}')
            else:
                value = float(val)
            if not row.get('start'):
                flags.append('instant')
            facts.append({
                'cik': cik,
                'entity_name': payload.get('entityName') or '',
                'taxonomy': payload.get('taxonomy') or request.taxonomy,
                'tag': payload.get('tag') or request.tag,
                'unit': unit,
                'period_start': row.get('start'),
                'period_end': row.get('end'),
                'value_num': value,
                'value_raw': '' if val is None else str(val),
                'fy': row.get('fy'),
                'fp': row.get('fp'),
                'form': row.get('form'),
                'filed': row.get('filed'),
                'accn': accn,
                'frame': row.get('frame'),
                'metric_id': request.metric_id,
                'filing_relation': filing_relation(row.get('form')),
                'selection_status': UNRESOLVED,
                'quality_flags': ','.join(flags),
                'snapshot_hash': snapshot_hash,
                'first_seen_at': seen_at,
                'last_seen_at': seen_at,
            })
    return facts, None


def plan_selection(facts):
    """One accession per (entity, tag, unit, period) is current; the rest are superseded.

    Ordering is by filed date then accession, both deterministic. An amended filing therefore
    wins over the original without deleting it.
    """
    groups = defaultdict(list)
    for fact in facts:
        key = (fact['cik'], fact['taxonomy'], fact['tag'], fact['unit'],
               fact['period_start'], fact['period_end'])
        groups[key].append(fact)
    plan = []
    for key, items in groups.items():
        # Without a filed date for every member the ordering is not evidenced; leave the group
        # unresolved rather than picking a winner by accession alone.
        if any(not f.get('filed') for f in items):
            continue
        chosen = sorted(items, key=lambda f: (f['filed'], f['accn']))[-1]
        plan.append((key, chosen['accn']))
    return plan


def can_derive_quarter(ytd_current, ytd_prior):
    """The six conditions from the design doc §3.4 rule 4.

    Returns (ok, reasons). Derivation is not persisted in phase 1; callers may report it only
    when ok is True and every condition is evidenced by the inputs themselves.
    """
    reasons = []
    if not ytd_current or not ytd_prior:
        return False, ['missing_input']
    for field in ('cik', 'taxonomy', 'tag', 'unit'):
        if ytd_current.get(field) != ytd_prior.get(field):
            reasons.append(f'{field}_mismatch')
    if ytd_current.get('fy') != ytd_prior.get('fy'):
        reasons.append('different_fiscal_year')
    if ytd_current.get('period_start') != ytd_prior.get('period_start'):
        reasons.append('different_ytd_start')
    cur_end, prior_end = ytd_current.get('period_end'), ytd_prior.get('period_end')
    if not cur_end or not prior_end or cur_end <= prior_end:
        reasons.append('period_not_after_prior')
    if ytd_current.get('value_num') is None or ytd_prior.get('value_num') is None:
        reasons.append('missing_value')
    if ytd_current.get('quality_flags', '').find('missing_value') >= 0:
        reasons.append('flagged_current')
    return (not reasons), reasons


def derive_quarter(ytd_current, ytd_prior):
    """Value of the quarter implied by two cumulative facts, or None when conditions fail."""
    ok, _ = can_derive_quarter(ytd_current, ytd_prior)
    if not ok:
        return None
    return ytd_current['value_num'] - ytd_prior['value_num']
