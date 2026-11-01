"""EIA API v2 client and normaliser — independent channel.

Scope (G-D2): the single verified route / metric / facet combination only.
  route   /v2/electricity/electric-power-operational-data/data/
  metric  generation (Utility Scale Electricity Net Generation)
  facets  location=US, sectorid=99, fueltypeid=COW
Anything else is out of scope and must be rejected rather than guessed.
"""
from __future__ import annotations
import urllib.parse
from dataclasses import dataclass

from . import http
from .http import IngestError

DATASET = 'electric-power-operational-data'
ROUTE = '/electricity/electric-power-operational-data/data/'
METRIC = 'generation'
UNIT_FIELD = 'generation-units'
EXPECTED_UNIT = 'thousand megawatthours'
MAX_PAGE = 5000

ALLOWED_FACETS = {'location': {'US'}, 'sectorid': {'99'}, 'fueltypeid': {'COW'}}


@dataclass(frozen=True)
class Query:
    frequency: str
    start: str
    end: str
    location: str = 'US'
    sectorid: str = '99'
    fueltypeid: str = 'COW'

    def __post_init__(self):
        if self.frequency not in {'monthly', 'annual'}:
            raise IngestError(http.SCHEMA, f'unsupported frequency: {self.frequency}')
        for name, value in (('location', self.location), ('sectorid', self.sectorid),
                            ('fueltypeid', self.fueltypeid)):
            allowed = ALLOWED_FACETS[name]
            if value not in allowed:
                raise IngestError(http.EMPTY_RESULT,
                                  f'facet {name}={value!r} is not in the verified whitelist '
                                  f'(allowed: {sorted(allowed)})')

    @property
    def series_id(self):
        return (f'eia:{DATASET}:{self.location}:{self.sectorid}:{self.fueltypeid}:'
                f'{METRIC}:{self.frequency}')

    def params(self, offset=0, length=MAX_PAGE):
        return [('frequency', self.frequency), ('data[0]', METRIC),
                ('facets[location][]', self.location), ('facets[sectorid][]', self.sectorid),
                ('facets[fueltypeid][]', self.fueltypeid),
                ('start', self.start), ('end', self.end),
                ('length', str(length)), ('offset', str(offset))]


class EiaClient:
    def __init__(self, settings, transport=None, limiter=None, sleep=None):
        self.settings = settings
        self.transport = transport or http.UrllibTransport()
        self.limiter = limiter
        kwargs = {} if sleep is None else {'sleep': sleep}
        self._get_kwargs = kwargs
        self.requests = 0

    def _url(self, query, offset, length):
        pairs = query.params(offset, length) + [('api_key', self.settings.eia_api_key)]
        return (self.settings.eia_base_url + ROUTE + '?'
                + urllib.parse.urlencode(pairs, safe='[]'))

    def url_without_secret(self, query, offset, length):
        return (self.settings.eia_base_url + ROUTE + '?'
                + urllib.parse.urlencode(query.params(offset, length), safe='[]'))

    def fetch_page(self, query, offset=0, length=MAX_PAGE, run_id=None, store=None):
        """One page. Records a raw snapshot; never logs or stores the api_key."""
        payload = http.get_json(self.transport, self._url(query, offset, length),
                                headers={'Accept': 'application/json'},
                                timeout=self.settings.timeout, limiter=self.limiter,
                                **self._get_kwargs)
        self.requests += 1
        if store is not None:
            body = __import__('json').dumps(payload, ensure_ascii=False).encode('utf-8')
            store.save_snapshot('eia', self.url_without_secret(query, offset, length),
                                f'{query.series_id}|offset={offset}', 200, body)
        return payload

    def fetch_all(self, query, store=None):
        """Paginate until accumulated rows reach `total`; a short read is truncation, not success."""
        rows, offset, total = [], 0, None
        while True:
            payload = self.fetch_page(query, offset=offset, run_id=None, store=store)
            response = payload.get('response') or {}
            if total is None:
                total = _as_int(response.get('total'))
                if total is None:
                    raise IngestError(http.SCHEMA, 'response.total missing or not numeric')
            data = response.get('data')
            if not isinstance(data, list):
                raise IngestError(http.SCHEMA, 'response.data is not a list')
            rows.extend(data)
            if total == 0:
                raise IngestError(http.EMPTY_RESULT,
                                  'query returned an empty set; an invalid facet looks identical '
                                  'to a legitimate empty result (200 + total=0)')
            if len(rows) >= total:
                break
            if not data:
                break
            offset += len(data)
            if offset > total + MAX_PAGE:
                raise IngestError(http.SCHEMA, 'pagination did not converge')
        if len(rows) != total:
            raise IngestError(http.TRUNCATION, f'collected {len(rows)} rows, API total is {total}')
        return rows


def _as_int(value):
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def normalize(query, rows, snapshot_hash, seen_at):
    """Validate the whole batch, then map to observation records.

    The batch is rejected as a unit when any row breaks the schema: a half-parsed series is
    worse than no series. Values stay strings; parsing to float is stored alongside.
    """
    if not rows:
        raise IngestError(http.EMPTY_RESULT, 'no rows to normalise')
    observations = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise IngestError(http.SCHEMA, f'row {index} is not an object')
        period = row.get('period')
        if not isinstance(period, str) or not period:
            raise IngestError(http.SCHEMA, f'row {index} has no period')
        if UNIT_FIELD not in row:
            raise IngestError(http.SCHEMA,
                              f'row {index} ({period}) has no {UNIT_FIELD}; refusing to assume a unit')
        unit = row.get(UNIT_FIELD)
        if unit != EXPECTED_UNIT:
            raise IngestError(http.SCHEMA, f'row {index} ({period}) unit is {unit!r}, '
                                           f'expected {EXPECTED_UNIT!r}')
        raw = row.get(METRIC)
        flags = []
        if isinstance(raw, str):
            try:
                value = float(raw)
            except ValueError:
                raise IngestError(http.SCHEMA, f'row {index} ({period}) value is not numeric: {raw!r}')
        elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
            value = float(raw)
            flags.append('schema_drift')
        else:
            raise IngestError(http.SCHEMA, f'row {index} ({period}) has no usable {METRIC}')
        observations.append({
            'series_id': query.series_id,
            'period': period,
            'value_raw': raw if isinstance(raw, str) else repr(raw),
            'value_num': value,
            'unit': unit,
            'period_kind': query.frequency,
            'is_partial_year': 0,
            'quality_flags': ','.join(flags),
            'snapshot_hash': snapshot_hash,
            'first_seen_at': seen_at,
            'last_seen_at': seen_at,
        })
    return observations


def series_meta(query, payload):
    response = payload.get('response') or {}
    return {
        'series_id': query.series_id,
        'dataset': DATASET,
        'route': ROUTE,
        'metric': METRIC,
        'unit': EXPECTED_UNIT,
        'frequency': query.frequency,
        'description': str(response.get('description') or '')[:500],
    }


def year_to_date(observations, year):
    """Explicit YTD helper: a sum of observed months, never stored as an annual observation."""
    months = sorted(o['period'] for o in observations
                    if o['period_kind'] == 'monthly' and o['period'].startswith(f'{year}-'))
    total = sum(o['value_num'] for o in observations
                if o['period_kind'] == 'monthly' and o['period'].startswith(f'{year}-'))
    return {'year': year, 'months_observed': len(months), 'first': months[0] if months else None,
            'last': months[-1] if months else None, 'sum_gwh': round(total, 5),
            'is_partial_year': len(months) < 12}
