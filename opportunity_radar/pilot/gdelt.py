"""GDELT DOC 2.0 discovery client and normaliser.

GDELT is an aggregator. This module only produces discovery candidates: URL, title,
domain, language and time. It never stores an upstream article body and never creates
evidence or claims.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sqlite3
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from opportunity_radar.ingest.http import (
    EMPTY_RESULT, RATE_LIMIT, SCHEMA, SERVER, TIMEOUT,
    IngestError, RateLimiter, UrllibTransport, classify,
)
from opportunity_radar.source_policy import is_approved, load_sources
from opportunity_radar.store import Store
from opportunity_radar.unified import canonical_url

SOURCE_ID = 'gdelt'
MAX_TITLE = 1000


def now():
    return datetime.now(timezone.utc).isoformat()


def _utc(value):
    text = str(value or '').strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None


def _stamp(value):
    return value.astimezone(timezone.utc).strftime('%Y%m%d%H%M%S')


@dataclass(frozen=True)
class GdeltResponse:
    status: int
    body: bytes
    payload: dict
    url: str
    headers: dict


@dataclass(frozen=True)
class GdeltWindow:
    timespan: str = ''
    startdatetime: str = ''
    enddatetime: str = ''

    def request_key(self):
        return '|'.join((self.timespan, self.startdatetime, self.enddatetime))


class GdeltClient:
    def __init__(self, settings, transport=None, limiter=None, sleep=time.sleep):
        self.settings = settings
        self.transport = transport or UrllibTransport()
        self.limiter = limiter or RateLimiter(
            0 if settings.gdelt_min_interval <= 0 else 1.0 / settings.gdelt_min_interval
        )
        self._sleep = sleep
        self.requests = 0
        self.last_request_at = None
        self.last_response = None

    def headers(self):
        return {'User-Agent': self.settings.user_agent, 'Accept': 'application/json'}

    def build_url(self, query, window, max_records):
        params = {
            'query': query,
            'mode': 'artlist',
            'format': 'json',
            'maxrecords': str(max_records),
            'sort': 'datedesc',
        }
        if window.timespan:
            params['timespan'] = window.timespan
        if window.startdatetime:
            params['startdatetime'] = window.startdatetime
        if window.enddatetime:
            params['enddatetime'] = window.enddatetime
        return f'{self.settings.gdelt_base_url}?{urllib.parse.urlencode(params)}'

    def fetch(self, query, window, max_records=None, attempts=3, retry_rate_limit=True):
        url = self.build_url(query, window, max_records or self.settings.max_records)
        self.last_response = None
        attempts = max(1, min(3, attempts))
        last = None
        for attempt in range(attempts):
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
                if attempt == attempts - 1 or (not exc.retryable and exc.error_class != TIMEOUT):
                    raise
                self._sleep(max(2, 2 ** (attempt + 1)))
                continue
            kind = classify(response.status)
            if kind:
                last = IngestError(kind, f'HTTP {response.status}', response.status,
                                   retryable=kind in {RATE_LIMIT, SERVER, TIMEOUT})
                if attempt == attempts - 1 or not last.retryable:
                    raise last
                if kind == RATE_LIMIT and not retry_rate_limit:
                    raise last
                if kind == RATE_LIMIT:
                    self._sleep(max(self.settings.gdelt_min_interval, 5 * (attempt + 1)))
                else:
                    self._sleep(max(2, 2 ** (attempt + 1)))
                continue

            body = (response.body or b'').strip()
            if not body:
                raise IngestError(EMPTY_RESULT, 'GDELT returned an empty body', response.status)
            if body[:1] != b'{':
                text = body[:240].decode('utf-8', 'replace')
                lowered = text.lower()
                if 'limit request' in lowered or 'rate limit' in lowered or 'too many' in lowered:
                    last = IngestError(RATE_LIMIT, f'GDELT throttle: {text}', response.status,
                                       retryable=True)
                    if attempt == attempts - 1 or not retry_rate_limit:
                        raise last
                    self._sleep(max(self.settings.gdelt_min_interval, 2 ** attempt))
                    continue
                raise IngestError(SCHEMA, f'GDELT returned non-JSON: {text}', response.status)
            try:
                payload = json.loads(body.decode('utf-8'))
            except (ValueError, UnicodeDecodeError) as exc:
                raise IngestError(SCHEMA, f'GDELT JSON parse failed: {exc}', response.status) from exc
            if not isinstance(payload, dict):
                raise IngestError(SCHEMA, 'GDELT payload is not an object', response.status)
            if payload.get('error'):
                raise IngestError(SCHEMA, f'GDELT error: {payload.get("error")}', response.status)
            if not isinstance(payload.get('articles'), list):
                # A 200 with `{}` is what GDELT has returned when a query is throttled or
                # rejected. It is not evidence of "no news"; make the run show it.
                raise IngestError(
                    EMPTY_RESULT,
                    'GDELT payload has no articles list (possible throttle or rejected query)',
                    response.status,
                )
            return GdeltResponse(response.status, body, payload, url, response.headers)
        raise last or IngestError(SERVER, 'GDELT request exhausted retries')


def clean_title(value):
    text = html.unescape(str(value or ''))
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:MAX_TITLE]


def body_preview(body, limit=500):
    return (body or b'')[:limit].decode('utf-8', 'replace')


def normalize_article(article, observed_at=None):
    """Return a discovery candidate or None for an unusable URL."""
    if not isinstance(article, dict):
        return None
    raw_url = str(article.get('url') or '').strip()
    canonical = canonical_url(raw_url)
    if not canonical:
        return None
    parsed = urllib.parse.urlsplit(canonical)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        return None
    domain = str(article.get('domain') or parsed.hostname or '').strip().lower()
    domain = domain[4:] if domain.startswith('www.') else domain
    if not domain:
        return None
    seen = str(article.get('seendate') or '').strip()
    title = clean_title(article.get('title'))
    observed = observed_at or now()
    candidate_id = hashlib.sha256(f'{SOURCE_ID}|{canonical}'.encode('utf-8')).hexdigest()
    return {
        'candidate_id': candidate_id,
        'source_id': SOURCE_ID,
        'url': raw_url,
        'canonical_url': canonical,
        'domain': domain,
        'title': title,
        'first_seen_at': observed,
        'last_seen_at': observed,
        'matched_article_key': None,
        'matched_event_id': None,
        'approved_source_id': None,
        'resolution_status': 'new',
        'lineage_role': 'aggregator',
        'evidence_role': 'discovery',
        'seendate': seen,
        'language': str(article.get('language') or '').strip(),
        'source_country': str(article.get('sourcecountry')
                              or article.get('source_country') or '').strip(),
    }


class ProductionIndex:
    """Read-only lookup of production articles and their events."""

    def __init__(self, path):
        self.path = Path(path)
        self.available = False
        self.by_key = {}
        self.by_canonical = {}
        self.event_by_article = {}
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            conn = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)
            conn.row_factory = sqlite3.Row
        except sqlite3.Error:
            return
        try:
            has_articles = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='articles'"
            ).fetchone()
            if not has_articles:
                return
            columns = {row[1] for row in conn.execute('PRAGMA table_info(articles)')}
            if 'url' not in columns or 'article_key' not in columns:
                return
            for row in conn.execute('SELECT article_key,url,title,published,source_name FROM articles'):
                key = row['article_key']
                self.by_key[key] = dict(row)
                canonical = canonical_url(row['url'])
                if canonical and canonical not in self.by_canonical:
                    self.by_canonical[canonical] = dict(row)
            has_events = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='event_articles'"
            ).fetchone()
            if has_events:
                for row in conn.execute('SELECT article_key,event_id FROM event_articles'):
                    self.event_by_article.setdefault(row['article_key'], row['event_id'])
            self.available = True
        except sqlite3.Error:
            self.available = False
        finally:
            conn.close()

    def match(self, url, canonical):
        row = self.by_key.get(Store.key(url))
        if row is None:
            row = self.by_canonical.get(canonical)
        if row is None:
            return None
        return row, self.event_by_article.get(row['article_key'])


def _normalise_domain(value):
    text = str(value or '').strip().lower()
    return text[4:] if text.startswith('www.') else text


class DomainRegistry:
    """Approved and merely registered domains from the existing source registry."""

    def __init__(self, approved=None, registered=None):
        self.approved = {_normalise_domain(k): v for k, v in (approved or {}).items() if k}
        self.registered = {_normalise_domain(k): v for k, v in (registered or {}).items() if k}

    @classmethod
    def from_sources(cls, path=None):
        if path is None:
            configured = os.environ.get('OR_SOURCES_PATH', '').strip()
            if configured:
                path = configured
            elif Path('config/sources.local.csv').exists():
                path = 'config/sources.local.csv'
            else:
                path = 'config/sources.csv'
        approved = {}
        registered = {}
        for source in load_sources(path):
            domain = _normalise_domain(source.canonical_domain)
            if not domain:
                continue
            registered.setdefault(domain, source.source_id)
            if is_approved(source):
                approved.setdefault(domain, source.source_id)
        return cls(approved, registered)

    def _match(self, domain, mapping):
        domain = _normalise_domain(domain)
        if not domain:
            return None
        if domain in mapping:
            return mapping[domain]
        best = None
        for candidate, source_id in mapping.items():
            if domain.endswith('.' + candidate) and (best is None or len(candidate) > len(best[0])):
                best = (candidate, source_id)
        return best[1] if best else None

    def classify(self, domain):
        approved = self._match(domain, self.approved)
        if approved:
            return approved, 'approved_source'
        if self._match(domain, self.registered):
            return None, 'unapproved_domain'
        return None, 'unknown_domain'


def match_candidate(candidate, production, domains):
    """Apply read-only article/event matching and domain status to one candidate."""
    matched = production.match(candidate['url'], candidate['canonical_url'])
    if matched:
        article, event_id = matched
        candidate['matched_article_key'] = article['article_key']
        candidate['matched_event_id'] = event_id
        approved_source_id, _ = domains.classify(candidate['domain'])
        candidate['approved_source_id'] = approved_source_id
        candidate['resolution_status'] = 'duplicate_article'
        return candidate
    approved_source_id, status = domains.classify(candidate['domain'])
    candidate['approved_source_id'] = approved_source_id
    candidate['resolution_status'] = status
    return candidate


def window_for_query(query, watermark, timespan_override=None):
    if timespan_override:
        return GdeltWindow(timespan=timespan_override)
    if watermark and watermark.get('last_success_at'):
        last = _utc(watermark['last_success_at'])
        if last:
            start = last - timedelta(hours=1)
            return GdeltWindow(startdatetime=_stamp(start), enddatetime=_stamp(datetime.now(timezone.utc)))
    return GdeltWindow(timespan=query.timespan or '7d')


def run_gdelt(settings, store, queries, timespan=None, query_ids=None,
              limit_queries=None, dry_run=False, client=None, config_hash='',
              query_hash='', report_writer=None, controlled=False):
    from .rights import assert_source_allowed

    assert_source_allowed(SOURCE_ID)
    selected = [query for query in queries if query.enabled]
    if query_ids:
        wanted = set(query_ids)
        selected = [query for query in selected if query.query_id in wanted]
    if limit_queries:
        selected = selected[:limit_queries]
    if not selected:
        raise ValueError('no enabled GDELT queries selected')

    plans = []
    if dry_run:
        for query in selected:
            watermark = store.get_watermark(SOURCE_ID, query.query_id)
            plans.append({'query_id': query.query_id, 'window': window_for_query(
                query, watermark, timespan).__dict__})
        return {'dry_run': True, 'source_id': SOURCE_ID, 'plans': plans}

    started = time.monotonic()
    run_id = store.start_run(SOURCE_ID, config_hash=config_hash, query_hash=query_hash)
    production = ProductionIndex(settings.production_db)
    domains = DomainRegistry.from_sources()
    client = client or GdeltClient(settings)
    request_count = record_count = error_count = candidate_count = 0
    duplicate_count = invalid_count = link_count = truncated_count = 0
    query_summaries = []
    request_log = []
    last_error = ''

    for query in selected:
        watermark = store.get_watermark(SOURCE_ID, query.query_id)
        window = window_for_query(query, watermark, timespan)
        request_started = now()
        try:
            response = client.fetch(
                query.query, window, query.max_records,
                attempts=1 if controlled else 3,
                retry_rate_limit=not controlled,
            )
            request_log.append({
                'query_id': query.query_id,
                'requested_at': request_started,
                'url': response.url,
                'status': response.status,
                'headers': dict(response.headers),
                'body_bytes': len(response.body or b''),
                'body_preview': body_preview(response.body),
            })
            request_count += 1
            snapshot_hash, _ = store.save_snapshot(
                SOURCE_ID, response.url,
                f'{query.query_id}|{window.request_key()}|{query.max_records}',
                response.status, response.body,
                content_type=response.headers.get('Content-Type', 'application/json'),
                etag=response.headers.get('ETag', ''),
                last_modified=response.headers.get('Last-Modified', ''),
            )
            articles = response.payload.get('articles')
            if not isinstance(articles, list):
                raise IngestError(
                    EMPTY_RESULT,
                    'GDELT payload has no articles list (possible throttle or rejected query)',
                    response.status,
                )
            if len(articles) >= query.max_records:
                truncated_count += 1
            accepted = 0
            for article in articles:
                candidate = normalize_article(article)
                if candidate is None:
                    invalid_count += 1
                    continue
                candidate = match_candidate(candidate, production, domains)
                store.upsert_candidate(candidate)
                store.add_candidate_observation(
                    candidate['candidate_id'], query.query_id, candidate['seendate'],
                    candidate['title'], candidate['language'], candidate['source_country'],
                    snapshot_hash,
                )
                candidate_count += 1
                accepted += 1
                record_count += 1
                if candidate['resolution_status'] == 'duplicate_article':
                    duplicate_count += 1
                if candidate['matched_event_id']:
                    if store.record_link_candidate(
                        'discovery_candidate', candidate['candidate_id'],
                        'event', candidate['matched_event_id'],
                        'url_match', 'canonical_url', 1.0,
                        json.dumps({'url': candidate['url'], 'title': candidate['title']},
                                   ensure_ascii=False),
                    ):
                        link_count += 1
            store.set_watermark(
                SOURCE_ID, query.query_id, now(),
                max((str(item.get('seendate') or '') for item in articles), default=''),
                run_id,
            )
            query_summaries.append({
                'query_id': query.query_id, 'status': 'success',
                'window': window.__dict__, 'articles': len(articles),
                'accepted': accepted, 'snapshot_hash': snapshot_hash,
                'truncated': len(articles) >= query.max_records,
            })
        except IngestError as exc:
            error_count += 1
            last_error = f'{query.query_id}: {exc.error_class}: {exc.detail}'
            last_response = getattr(client, 'last_response', None)
            request_log.append({
                'query_id': query.query_id,
                'requested_at': request_started,
                'url': getattr(last_response, 'url', ''),
                'status': getattr(last_response, 'status', None),
                'headers': dict(getattr(last_response, 'headers', {}) or {}),
                'body_bytes': len(getattr(last_response, 'body', b'') or b''),
                'body_preview': body_preview(getattr(last_response, 'body', b'') or b''),
                'error_class': exc.error_class,
            })
            store.record_failure(run_id, SOURCE_ID, 'fetch/normalize',
                                 exc.error_class, exc.detail, query.query_id)
            query_summaries.append({
                'query_id': query.query_id, 'status': 'failed',
                'error_class': exc.error_class, 'detail': exc.detail,
                'window': window.__dict__,
            })
        except Exception as exc:  # noqa: BLE001 - one query must not abort the rest
            error_count += 1
            last_error = f'{query.query_id}: unexpected: {type(exc).__name__}: {exc}'
            last_response = getattr(client, 'last_response', None)
            request_log.append({
                'query_id': query.query_id,
                'requested_at': request_started,
                'url': getattr(last_response, 'url', ''),
                'status': getattr(last_response, 'status', None),
                'headers': dict(getattr(last_response, 'headers', {}) or {}),
                'body_bytes': len(getattr(last_response, 'body', b'') or b''),
                'body_preview': body_preview(getattr(last_response, 'body', b'') or b''),
                'error_class': SERVER,
            })
            store.record_failure(run_id, SOURCE_ID, 'unexpected', SERVER,
                                 f'{type(exc).__name__}: {exc}', query.query_id)
            query_summaries.append({
                'query_id': query.query_id, 'status': 'failed',
                'error_class': SERVER, 'detail': str(exc), 'window': window.__dict__,
            })

    status = 'success' if error_count == 0 else ('failed' if record_count == 0 else 'partial_failed')
    http_requests = getattr(client, 'requests', request_count)
    store.finish_run(
        run_id, status, requests=http_requests, records=record_count, errors=error_count,
        message=last_error, exit_code=0 if status == 'success' else 1,
    )
    resolution_counts = store.candidate_stats(run_id)
    summary = {
        'source_id': SOURCE_ID, 'run_id': run_id, 'status': status,
        'started_at': store.latest_run(SOURCE_ID)['started_at'],
        'finished_at': store.latest_run(SOURCE_ID)['finished_at'],
        'seconds': round(time.monotonic() - started, 2),
        'requests': http_requests, 'queries_succeeded': request_count,
        'records': record_count, 'errors': error_count,
        'candidate_observations': candidate_count,
        'unique_candidates': sum(resolution_counts.values()),
        'duplicates': duplicate_count,
        'invalid': invalid_count, 'links_created': link_count,
        'truncated_queries': truncated_count,
        'resolution_counts': resolution_counts,
        'production_index_available': production.available,
        'controlled': controlled,
        'requests_log': request_log,
        'queries': query_summaries,
        'config_hash': config_hash, 'query_hash': query_hash,
    }
    if report_writer:
        report_writer(store, run_id, settings, summary)
    return summary
