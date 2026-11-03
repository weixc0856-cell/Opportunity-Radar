"""Federal Register policy-document pilot.

The module only writes pilot policy records. It never creates an Article, event,
evidence or claim, and never writes the production RSS database.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from opportunity_radar.ingest.http import (
    RATE_LIMIT, SCHEMA, SERVER, TIMEOUT,
    IngestError, RateLimiter, UrllibTransport, classify,
)

SOURCE_ID = 'federal-register'
BASE_FIELDS = [
    'document_number', 'title', 'type', 'publication_date', 'effective_on',
    'comments_close_on', 'citation', 'docket_ids', 'raw_text_url', 'html_url',
    'pdf_url', 'agencies', 'correction_of', 'corrections', 'abstract',
]
TYPE_MAP = {
    'rule': 'RULE',
    'proposed rule': 'PRORULE',
    'notice': 'NOTICE',
    'presidential document': 'PRESDOC',
}


def now():
    return datetime.now(timezone.utc).isoformat()


def _preview(body, limit=500):
    return (body or b'')[:limit].decode('utf-8', 'replace')


def _json(value):
    return json.dumps(value if value is not None else None, ensure_ascii=False,
                      sort_keys=True, separators=(',', ':'))


def _document_type(value):
    raw = str(value or '').strip()
    mapped = TYPE_MAP.get(raw.lower())
    if not mapped:
        raise ValueError(f'unknown Federal Register document type: {raw!r}')
    return mapped


def _agency_slugs(agencies):
    if not isinstance(agencies, list):
        return []
    return sorted({
        str(item.get('slug') or '').strip()
        for item in agencies
        if isinstance(item, dict) and str(item.get('slug') or '').strip()
    })


def normalize_document(document, observed_at=None):
    if not isinstance(document, dict):
        raise ValueError('Federal Register document is not an object')
    number = str(document.get('document_number') or '').strip()
    title = str(document.get('title') or '').strip()
    published = str(document.get('publication_date') or '').strip()
    if not number or not title or not published:
        raise ValueError('Federal Register document requires document_number, title and publication_date')
    document_type = _document_type(document.get('type'))
    agencies = document.get('agencies') if isinstance(document.get('agencies'), list) else []
    docket_ids = document.get('docket_ids')
    if not isinstance(docket_ids, list):
        docket_ids = []
    related = {
        'correction_of': document.get('correction_of'),
        'corrections': document.get('corrections') or [],
    }
    selected = {
        'document_number': number,
        'document_type': document_type,
        'title': title,
        'abstract': str(document.get('abstract') or '').strip(),
        'agencies_json': _json(agencies),
        'agency_slugs': ','.join(_agency_slugs(agencies)),
        'published_at': published,
        'effective_on': document.get('effective_on'),
        'comments_close_on': document.get('comments_close_on'),
        'docket_ids_json': _json(docket_ids),
        'citation': document.get('citation'),
        'html_url': document.get('html_url'),
        'pdf_url': document.get('pdf_url'),
        'raw_text_url': document.get('raw_text_url'),
        'related_document_numbers_json': _json(related),
    }
    content_hash = hashlib.sha256(_json(selected).encode('utf-8')).hexdigest()
    observed = observed_at or now()
    return {
        'document_id': 'fr:' + number,
        'source_id': SOURCE_ID,
        **selected,
        'content_hash': content_hash,
        'latest_snapshot_hash': '',
        'first_seen_at': observed,
        'last_seen_at': observed,
        'retrieved_at': observed,
        'fields_json': _json(selected),
    }


@dataclass(frozen=True)
class FederalRegisterResponse:
    status: int
    body: bytes
    payload: dict
    url: str
    headers: dict


class FederalRegisterClient:
    def __init__(self, settings, transport=None, limiter=None, sleep=time.sleep):
        self.settings = settings
        self.transport = transport or UrllibTransport()
        self.limiter = limiter or RateLimiter(
            0 if settings.fr_min_interval <= 0 else 1.0 / settings.fr_min_interval
        )
        self._sleep = sleep
        self.requests = 0
        self.last_request_at = None
        self.last_request_url = None
        self.last_response = None

    def headers(self):
        return {'User-Agent': self.settings.user_agent, 'Accept': 'application/json'}

    def build_url(self, watch, since, until=None, page=1, per_page=100):
        params = [
            ('per_page', str(per_page)),
            ('page', str(page)),
            ('order', 'newest'),
            ('conditions[agencies][]', watch.agency_slug),
            ('conditions[term]', watch.term),
            ('conditions[publication_date][gte]', since),
        ]
        if until:
            params.append(('conditions[publication_date][lte]', until))
        for document_type in watch.types:
            params.append(('conditions[type][]', document_type))
        for field in BASE_FIELDS:
            params.append(('fields[]', field))
        return f'{self.settings.fr_base_url}/documents.json?{urllib.parse.urlencode(params)}'

    def fetch(self, watch, since, until=None, page=1, per_page=100):
        url = self.build_url(watch, since, until, page, per_page)
        self.last_response = None
        self.last_request_url = url
        last = None
        for attempt in range(3):
            self.limiter.wait()
            self.requests += 1
            self.last_request_at = now()
            try:
                response = self.transport.get(
                    url, headers=self.headers(), timeout=self.settings.timeout
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
            body = (response.body or b'').strip()
            if not body:
                raise IngestError(SCHEMA, 'Federal Register returned an empty body', response.status)
            try:
                payload = json.loads(body.decode('utf-8'))
            except (ValueError, UnicodeDecodeError) as exc:
                raise IngestError(SCHEMA, f'Federal Register JSON parse failed: {exc}',
                                  response.status) from exc
            if not isinstance(payload, dict):
                raise IngestError(SCHEMA, 'Federal Register payload is not an object',
                                  response.status)
            results = payload.get('results')
            if not isinstance(results, list):
                # Federal Register returns {"description": "...", "count": 0} for a
                # zero-result query, with no results/total_pages keys. That is a valid
                # empty result, not a schema failure.
                if payload.get('count') == 0:
                    payload = dict(payload)
                    payload['results'] = []
                    payload['total_pages'] = 0
                    results = []
                else:
                    raise IngestError(SCHEMA, 'Federal Register payload has no results list',
                                      response.status)
            return FederalRegisterResponse(response.status, body, payload, url, response.headers)
        raise last or IngestError(SERVER, 'Federal Register request exhausted retries')


def default_since(days=7):
    return (date.today() - timedelta(days=days)).isoformat()


def run_federal_register(settings, store, watches, since=None, until=None,
                         max_pages=5, max_documents=200, watch_ids=None,
                         limit_watches=None, dry_run=False, client=None,
                         config_hash='', query_hash='', report_writer=None):
    from .rights import assert_source_allowed

    assert_source_allowed(SOURCE_ID)
    selected = [watch for watch in watches if watch.enabled]
    if watch_ids:
        wanted = set(watch_ids)
        selected = [watch for watch in selected if watch.watch_id in wanted]
    if limit_watches:
        selected = selected[:limit_watches]
    if not selected:
        raise ValueError('no enabled Federal Register watch rows selected')
    since = since or default_since()
    max_pages = max(1, min(5, int(max_pages)))
    max_documents = max(1, min(200, int(max_documents)))

    if dry_run:
        return {
            'dry_run': True, 'source_id': SOURCE_ID, 'since': since, 'until': until,
            'max_pages': max_pages, 'max_documents': max_documents,
            'watches': [{'watch_id': watch.watch_id, 'agency_slug': watch.agency_slug,
                         'term': watch.term, 'types': watch.types} for watch in selected],
        }

    started = time.monotonic()
    run_id = store.start_run(SOURCE_ID, config_hash=config_hash, query_hash=query_hash)
    client = client or FederalRegisterClient(settings)
    request_log = []
    query_summaries = []
    seen_documents = set()
    counts = {'inserted': 0, 'updated': 0, 'unchanged': 0, 'duplicates': 0,
              'invalid': 0, 'errors': 0, 'requests': 0, 'pages': 0}
    total_documents = 0
    truncated = False
    last_error = ''

    for watch in selected:
        if total_documents >= max_documents:
            truncated = True
            break
        page = 1
        watch_documents = 0
        watch_truncated = False
        watch_requests = 0
        watch_failed = False
        while page <= max_pages:
            request_started = now()
            try:
                response = client.fetch(watch, since, until, page)
                counts['requests'] += 1
                counts['pages'] += 1
                watch_requests += 1
                request_log.append({
                    'watch_id': watch.watch_id,
                    'requested_at': request_started,
                    'url': response.url,
                    'status': response.status,
                    'headers': dict(response.headers),
                    'body_bytes': len(response.body or b''),
                    'body_preview': _preview(response.body),
                    'page': page,
                })
                snapshot_hash, _ = store.save_snapshot(
                    SOURCE_ID, response.url,
                    f'{watch.watch_id}|{since}|{until or ""}|{page}|100',
                    response.status, response.body,
                    content_type=response.headers.get('Content-Type', 'application/json'),
                    etag=response.headers.get('ETag', ''),
                    last_modified=response.headers.get('Last-Modified', ''),
                )
                results = response.payload.get('results') or []
                total_pages = int(response.payload.get('total_pages') or 0)
                for document in results:
                    number = str(document.get('document_number') or '').strip()
                    if number and number in seen_documents:
                        counts['duplicates'] += 1
                        continue
                    if total_documents >= max_documents or watch_documents >= watch.max_documents:
                        watch_truncated = True
                        break
                    try:
                        normalized = normalize_document(document)
                    except ValueError as exc:
                        counts['invalid'] += 1
                        store.record_failure(run_id, SOURCE_ID, 'normalize', SCHEMA,
                                             f'{number or "unknown"}: {exc}', watch.watch_id)
                        continue
                    normalized['latest_snapshot_hash'] = snapshot_hash
                    outcome = store.upsert_policy_document(normalized)
                    counts[outcome] += 1
                    seen_documents.add(number)
                    total_documents += 1
                    watch_documents += 1
                if watch_truncated or not results:
                    break
                if total_pages and page >= total_pages:
                    break
                page += 1
            except IngestError as exc:
                watch_failed = True
                counts['errors'] += 1
                last_error = f'{watch.watch_id}: {exc.error_class}: {exc.detail}'
                last_response = getattr(client, 'last_response', None)
                request_log.append({
                    'watch_id': watch.watch_id,
                    'requested_at': request_started,
                    'url': getattr(client, 'last_request_url', '') or
                           getattr(last_response, 'url', ''),
                    'status': getattr(last_response, 'status', None),
                    'headers': dict(getattr(last_response, 'headers', {}) or {}),
                    'body_bytes': len(getattr(last_response, 'body', b'') or b''),
                    'body_preview': _preview(getattr(last_response, 'body', b'') or b''),
                    'page': page,
                    'error_class': exc.error_class,
                })
                store.record_failure(run_id, SOURCE_ID, 'fetch/normalize',
                                     exc.error_class, exc.detail, watch.watch_id)
                query_summaries.append({
                    'watch_id': watch.watch_id, 'status': 'failed',
                    'error_class': exc.error_class, 'detail': exc.detail,
                    'page': page, 'documents': watch_documents,
                })
                break
            except Exception as exc:  # noqa: BLE001 - one watch must not abort the rest
                watch_failed = True
                counts['errors'] += 1
                last_error = f'{watch.watch_id}: unexpected: {type(exc).__name__}: {exc}'
                store.record_failure(run_id, SOURCE_ID, 'unexpected', SERVER,
                                     f'{type(exc).__name__}: {exc}', watch.watch_id)
                query_summaries.append({
                    'watch_id': watch.watch_id, 'status': 'failed',
                    'error_class': SERVER, 'detail': str(exc), 'page': page,
                    'documents': watch_documents,
                })
                break
        if not watch_failed:
            query_summaries.append({
                'watch_id': watch.watch_id, 'status': 'truncated' if watch_truncated else 'success',
                'page': page, 'documents': watch_documents,
                'requests': watch_requests, 'truncated': watch_truncated,
            })
        if watch_truncated:
            truncated = True

    status = 'success' if counts['errors'] == 0 else (
        'failed' if total_documents == 0 else 'partial_failed')
    http_requests = getattr(client, 'requests', counts['requests'])
    store.finish_run(run_id, status, requests=http_requests, records=total_documents,
                     errors=counts['errors'], message=last_error,
                     exit_code=0 if status == 'success' else 1)
    summary = {
        'source_id': SOURCE_ID, 'run_id': run_id, 'status': status,
        'started_at': store.latest_run(SOURCE_ID)['started_at'],
        'finished_at': store.latest_run(SOURCE_ID)['finished_at'],
        'seconds': round(time.monotonic() - started, 2),
        'since': since, 'until': until,
        'requests': http_requests, 'pages': counts['pages'],
        'documents': total_documents,
        'inserted': counts['inserted'], 'updated': counts['updated'],
        'unchanged': counts['unchanged'], 'duplicates': counts['duplicates'],
        'invalid': counts['invalid'], 'errors': counts['errors'],
        'truncated': truncated, 'by_type': store.policy_stats(run_id),
        'version_count': store.policy_version_count(),
        'requests_log': request_log, 'watches': query_summaries,
        'config_hash': config_hash, 'query_hash': query_hash,
    }
    if report_writer:
        report_writer(store, run_id, settings, summary)
    return summary
