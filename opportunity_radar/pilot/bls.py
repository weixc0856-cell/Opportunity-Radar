"""BLS Public Data API v1 macro-series pilot.

One POST fetches all enabled series. The module writes only the pilot macro tables; it
never writes production, events, evidence or claims.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from opportunity_radar.ingest.http import (
    EMPTY_RESULT, RATE_LIMIT, SCHEMA, SERVER, TIMEOUT,
    IngestError, RateLimiter, Response, classify,
)

SOURCE_ID = 'bls'
MAX_SERIES = 25
MAX_YEARS = 10


def now():
    return datetime.now(timezone.utc).isoformat()


def _preview(body, limit=500):
    return (body or b'')[:limit].decode('utf-8', 'replace')


def _json(value):
    return json.dumps(value if value is not None else None, ensure_ascii=False,
                      sort_keys=True, separators=(',', ':'))


def _period(year, raw):
    raw = str(raw or '').strip().upper()
    year = str(year or '').strip()
    if not year or not raw:
        return None, 'unknown_period'
    if raw == 'M13':
        return year, ''
    if raw.startswith('M') and raw[1:].isdigit() and 1 <= int(raw[1:]) <= 12:
        return f'{year}-{int(raw[1:]):02d}', ''
    if raw.startswith('Q') and raw[1:].isdigit() and 1 <= int(raw[1:]) <= 4:
        return f'{year}-Q{int(raw[1:])}', ''
    return None, 'unknown_period'


def _preliminary(footnotes):
    if not isinstance(footnotes, list):
        return None
    for note in footnotes:
        if not isinstance(note, dict):
            continue
        code = str(note.get('code') or '').strip().upper()
        text = str(note.get('text') or '').lower()
        if code == 'P' or 'preliminary' in text:
            return 1
    return None


def _latest(value):
    if value is None:
        return None
    text = str(value).strip().lower()
    if text == 'true':
        return 1
    if text == 'false':
        return 0
    return None


def normalize_observation(data, series, snapshot_hash, observed_at=None):
    if not isinstance(data, dict):
        raise ValueError('BLS observation is not an object')
    year = str(data.get('year') or '').strip()
    period_raw = str(data.get('period') or '').strip().upper()
    if not year or not period_raw:
        raise ValueError('BLS observation requires year and period')
    period, period_flag = _period(year, period_raw)
    value_raw = data.get('value')
    if value_raw is None:
        value_raw = ''
    value_text = str(value_raw).strip()
    flags = []
    try:
        value_num = float(value_text)
    except (TypeError, ValueError):
        value_num = None
        flags.append('missing_value')
    if period_flag:
        flags.append(period_flag)
    footnotes = data.get('footnotes')
    if not isinstance(footnotes, list):
        footnotes = []
    observed = observed_at or now()
    return {
        'series_id': series.series_id,
        'year': year,
        'period_raw': period_raw,
        'period': period,
        'period_name': str(data.get('periodName') or '').strip(),
        'value_raw': value_text,
        'value_num': value_num,
        'unit': series.unit,
        'preliminary': _preliminary(footnotes),
        'latest': _latest(data.get('latest')),
        'footnotes_json': _json(footnotes),
        'quality_flags': ','.join(flags),
        'snapshot_hash': snapshot_hash,
        'first_seen_at': observed,
        'last_seen_at': observed,
        'observed_at': observed,
    }


def series_record(series, observed_at=None):
    observed = observed_at or now()
    return {
        'series_id': series.series_id,
        'source_id': SOURCE_ID,
        'label': series.label,
        'topic': series.topic,
        'unit': series.unit,
        'frequency': series.frequency,
        'seasonal_adjustment': series.seasonal_adjustment,
        'source_url': f'https://data.bls.gov/timeseries/{series.series_id}',
        'first_seen_at': observed,
        'last_seen_at': observed,
    }


@dataclass(frozen=True)
class BlsResponse:
    status: int
    body: bytes
    payload: dict
    url: str
    headers: dict


class UrllibPostTransport:
    def post(self, url, body, headers=None, timeout=30):
        request = urllib.request.Request(url, data=body, headers=headers or {},
                                         method='POST')
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return Response(response.status, response.read(), dict(response.headers))
        except urllib.error.HTTPError as exc:
            return Response(exc.code, exc.read(), dict(exc.headers))
        except (TimeoutError, urllib.error.URLError) as exc:
            if isinstance(getattr(exc, 'reason', None), (TimeoutError, TimeoutError)):
                raise IngestError(TIMEOUT, f'BLS timeout: {exc}') from exc
            raise IngestError(SERVER, f'BLS transport error: {exc}') from exc


class BlsClient:
    def __init__(self, settings, transport=None, limiter=None, sleep=time.sleep):
        self.settings = settings
        self.transport = transport or UrllibPostTransport()
        self.limiter = limiter or RateLimiter(
            0 if settings.bls_min_interval <= 0 else 1.0 / settings.bls_min_interval
        )
        self._sleep = sleep
        self.requests = 0
        self.last_request_at = None
        self.last_request_url = None
        self.last_response = None

    def headers(self):
        return {'User-Agent': self.settings.user_agent,
                'Content-Type': 'application/json',
                'Accept': 'application/json'}

    def build_url(self):
        return f'{self.settings.bls_base_url}/timeseries/data/'

    def fetch(self, series_ids, start_year, end_year):
        if not series_ids:
            raise ValueError('BLS fetch requires at least one series')
        if len(series_ids) > MAX_SERIES:
            raise ValueError(f'BLS v1 allows at most {MAX_SERIES} series per request')
        start_year = int(start_year)
        end_year = int(end_year)
        if end_year < start_year or end_year - start_year >= MAX_YEARS:
            raise ValueError(f'BLS v1 allows a range of fewer than {MAX_YEARS + 1} years')
        url = self.build_url()
        self.last_response = None
        self.last_request_url = url
        body = json.dumps({'seriesid': list(series_ids), 'startyear': str(start_year),
                           'endyear': str(end_year)}).encode('utf-8')
        last = None
        for attempt in range(3):
            self.limiter.wait()
            self.requests += 1
            self.last_request_at = now()
            try:
                response = self.transport.post(
                    url, body, headers=self.headers(), timeout=self.settings.timeout
                )
                self.last_response = response
            except IngestError as exc:
                last = exc
                if attempt == 2 or (not exc.retryable and exc.error_class != TIMEOUT):
                    raise
                self._sleep(max(2, 2 ** (attempt + 1)))
                continue
            kind = classify(response.status)
            if kind:
                last = IngestError(kind, f'HTTP {response.status}', response.status,
                                   retryable=kind in {RATE_LIMIT, SERVER, TIMEOUT})
                if attempt == 2 or not last.retryable:
                    raise last
                self._sleep(max(2, 2 ** (attempt + 1)))
                continue
            try:
                payload = json.loads(response.body.decode('utf-8'))
            except (ValueError, UnicodeDecodeError) as exc:
                raise IngestError(SCHEMA, f'BLS JSON parse failed: {exc}',
                                  response.status) from exc
            if not isinstance(payload, dict):
                raise IngestError(SCHEMA, 'BLS payload is not an object', response.status)
            if payload.get('status') != 'REQUEST_SUCCEEDED':
                message = _json(payload.get('message') or payload.get('status'))
                lowered = message.lower()
                cls = RATE_LIMIT if ('limit' in lowered or 'exceeded' in lowered) else SERVER
                raise IngestError(cls, f'BLS status {payload.get("status")}: {message}',
                                  response.status, retryable=cls == RATE_LIMIT)
            results = payload.get('Results')
            if not isinstance(results, dict) or not isinstance(results.get('series'), list):
                raise IngestError(SCHEMA, 'BLS payload has no Results.series list',
                                  response.status)
            if not results['series']:
                raise IngestError(EMPTY_RESULT, 'BLS returned no series', response.status)
            return BlsResponse(response.status, response.body, payload, url,
                               response.headers)
        raise last or IngestError(SERVER, 'BLS request exhausted retries')


def run_bls(settings, store, series_list, start_year, end_year,
            dry_run=False, client=None, config_hash='', query_hash='',
            report_writer=None):
    from .rights import assert_source_allowed

    assert_source_allowed(SOURCE_ID)
    selected = [series for series in series_list if series.enabled]
    if not selected:
        raise ValueError('no enabled BLS series selected')
    if len(selected) > MAX_SERIES:
        raise ValueError(f'BLS v1 allows at most {MAX_SERIES} series per request')
    start_year = int(start_year)
    end_year = int(end_year)
    if end_year < start_year or end_year - start_year >= MAX_YEARS:
        raise ValueError(f'BLS v1 allows a range of fewer than {MAX_YEARS + 1} years')

    if dry_run:
        return {
            'dry_run': True, 'source_id': SOURCE_ID, 'start_year': start_year,
            'end_year': end_year, 'url': (client.build_url() if client else
                                          f'{settings.bls_base_url}/timeseries/data/'),
            'series': [{'series_id': series.series_id, 'label': series.label,
                        'unit': series.unit, 'frequency': series.frequency,
                        'seasonal_adjustment': series.seasonal_adjustment}
                       for series in selected],
        }

    started = time.monotonic()
    run_id = store.start_run(SOURCE_ID, config_hash=config_hash, query_hash=query_hash)
    client = client or BlsClient(settings)
    request_started = now()
    counts = {'series': 0, 'observations': 0, 'inserted': 0, 'updated': 0,
              'unchanged': 0, 'missing_series': 0, 'invalid': 0, 'errors': 0}
    request_log = []
    series_summaries = []
    last_error = ''
    try:
        response = client.fetch([series.series_id for series in selected],
                                start_year, end_year)
        request_log.append({
            'requested_at': request_started,
            'url': response.url,
            'status': response.status,
            'headers': dict(response.headers),
            'body_bytes': len(response.body or b''),
            'body_preview': _preview(response.body),
        })
        snapshot_hash, _ = store.save_snapshot(
            SOURCE_ID, response.url,
            f'{start_year}-{end_year}|{",".join(series.series_id for series in selected)}',
            response.status, response.body,
            content_type=response.headers.get('Content-Type', 'application/json'),
            etag=response.headers.get('ETag', ''),
            last_modified=response.headers.get('Last-Modified', ''),
        )
        payload_series = {
            str(item.get('seriesID') or ''): item
            for item in response.payload.get('Results', {}).get('series', [])
            if isinstance(item, dict)
        }
        for series in selected:
            item = payload_series.get(series.series_id)
            if item is None:
                counts['missing_series'] += 1
                counts['errors'] += 1
                last_error = f'{series.series_id}: missing from BLS response'
                store.record_failure(run_id, SOURCE_ID, 'normalize', EMPTY_RESULT,
                                     last_error, series.series_id)
                series_summaries.append({'series_id': series.series_id,
                                         'status': 'missing'})
                continue
            data = item.get('data')
            if not isinstance(data, list) or not data:
                counts['errors'] += 1
                last_error = f'{series.series_id}: empty data list'
                store.record_failure(run_id, SOURCE_ID, 'normalize', EMPTY_RESULT,
                                     last_error, series.series_id)
                series_summaries.append({'series_id': series.series_id,
                                         'status': 'empty'})
                continue
            observed = now()
            record = series_record(series, observed)
            store.upsert_macro_series(record)
            counts['series'] += 1
            series_counts = {'series_id': series.series_id, 'status': 'success',
                             'observations': 0, 'inserted': 0, 'updated': 0,
                             'unchanged': 0, 'invalid': 0}
            for observation_data in data:
                try:
                    observation = normalize_observation(
                        observation_data, series, snapshot_hash, observed
                    )
                except ValueError as exc:
                    counts['invalid'] += 1
                    counts['errors'] += 1
                    series_counts['invalid'] += 1
                    store.record_failure(run_id, SOURCE_ID, 'normalize', SCHEMA,
                                         f'{series.series_id}: {exc}', series.series_id)
                    continue
                outcome = store.upsert_macro_observation(observation)
                counts[outcome] += 1
                series_counts[outcome] += 1
                counts['observations'] += 1
                series_counts['observations'] += 1
            series_summaries.append(series_counts)
    except IngestError as exc:
        counts['errors'] += 1
        last_error = f'{exc.error_class}: {exc.detail}'
        last_response = getattr(client, 'last_response', None)
        request_log.append({
            'requested_at': request_started,
            'url': getattr(client, 'last_request_url', ''),
            'status': getattr(last_response, 'status', None),
            'headers': dict(getattr(last_response, 'headers', {}) or {}),
            'body_bytes': len(getattr(last_response, 'body', b'') or b''),
            'body_preview': _preview(getattr(last_response, 'body', b'') or b''),
            'error_class': exc.error_class,
        })
        store.record_failure(run_id, SOURCE_ID, 'fetch', exc.error_class, exc.detail, '')
    except Exception as exc:  # noqa: BLE001 - one run failure must be visible
        counts['errors'] += 1
        last_error = f'{type(exc).__name__}: {exc}'
        store.record_failure(run_id, SOURCE_ID, 'unexpected', SERVER,
                             f'{type(exc).__name__}: {exc}', '')

    status = 'success' if counts['errors'] == 0 else (
        'failed' if counts['observations'] == 0 else 'partial_failed')
    http_requests = getattr(client, 'requests', len(request_log))
    store.finish_run(run_id, status, requests=http_requests,
                     records=counts['observations'], errors=counts['errors'],
                     message=last_error, exit_code=0 if status == 'success' else 1)
    summary = {
        'source_id': SOURCE_ID, 'run_id': run_id, 'status': status,
        'started_at': store.latest_run(SOURCE_ID)['started_at'],
        'finished_at': store.latest_run(SOURCE_ID)['finished_at'],
        'seconds': round(time.monotonic() - started, 2),
        'start_year': start_year, 'end_year': end_year,
        'requests': http_requests,
        'series_count': counts['series'],
        'observations': counts['observations'],
        'inserted': counts['inserted'], 'updated': counts['updated'],
        'unchanged': counts['unchanged'],
        'missing_series': counts['missing_series'], 'invalid': counts['invalid'],
        'errors': counts['errors'],
        'by_frequency': store.macro_stats(run_id),
        'version_count': store.macro_version_count(),
        'requests_log': request_log, 'series': series_summaries,
        'config_hash': config_hash, 'query_hash': query_hash,
    }
    if report_writer:
        report_writer(store, run_id, settings, summary)
    return summary
