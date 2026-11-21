"""Web-wide news discovery through public feeds and official APIs.

The goal is discovery, not scraping. Every provider below is a public RSS feed or an
explicit API; none of them requires bypassing a login, a paywall or a rate limit.

* `google_news` uses Google News RSS. Its copyright notice grants personal, non-commercial
  feed-reader use. It carries headline, publisher, date and a link, but no article summary.
* `gdelt` uses the public GDELT DOC 2.0 API. It adds geographic/language filters and original
  publisher URLs. It is rate-limited to one request every five seconds; that limit is
  enforced here, not ignored.
* `newsapi` and `brave` are optional and only run when their API key is configured. They
  return a publisher snippet and the original URL.
* `guardian` is optional and returns a trail text and body from the Guardian API.

Optional page fetching goes through `FullTextFetcher`, which reads robots.txt first,
refuses cross-host redirects, stops on 401/403/429, detects paywalls and never retries with
a different identity. A search snippet is enough to triage; a fetched page is still only
E1 because no reviewer has declared the source full-text.

The query registry is local and opt-in (`config/discovery_sources.json`). The tracked
example is disabled. Results are attributed to the publisher in `source_name`; the query
is the cap/monitoring source in `source_id`, so one query cannot crowd out a publisher.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from .freshrss_client import Article
from .fulltext import FullTextFetcher
from .source_policy import Source

DEFAULT_CONFIG = Path('config/discovery_sources.json')
EXAMPLE_CONFIG = Path('config/discovery_sources.example.json')
UA = 'OpportunityRadar-Discovery/0.1 (local personal research)'
TAG = re.compile(r'<[^>]+>')
SPACE = re.compile(r'\s+')
GOOGLE_NEWS = 'https://news.google.com/rss/search'
GDELT = 'https://api.gdeltproject.org/api/v2/doc/doc'
NEWSAPI = 'https://newsapi.org/v2/everything'
BRAVE = 'https://api.search.brave.com/res/v1/news/search'
GUARDIAN = 'https://content.guardianapis.com/search'
GDELT_MIN_INTERVAL = 5.0
_last_gdelt = 0.0


class DiscoveryUnavailable(RuntimeError):
    pass


@dataclass
class DiscoveryArticle(Article):
    source_id: str = ''
    discovery: dict | None = None


class Http:
    """Small injectable HTTP client; tests replace it instead of touching the network."""
    def get_text(self, url: str, headers: dict | None = None, timeout: int = 20) -> str:
        merged = {'User-Agent': UA, 'Accept-Encoding': 'identity'}
        merged.update(headers or {})
        request = urllib.request.Request(url, headers=merged)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode('utf-8', 'replace')
        except Exception as exc:
            raise DiscoveryUnavailable(f'{type(exc).__name__}: {exc}') from exc

    def get_json(self, url: str, headers: dict | None = None, timeout: int = 20) -> dict:
        text = self.get_text(url, headers, timeout)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DiscoveryUnavailable(f'invalid JSON: {exc}') from exc
        if not isinstance(data, dict):
            raise DiscoveryUnavailable('provider returned a non-object JSON payload')
        return data


def load_config(path=None) -> dict:
    target = Path(path or os.environ.get('OR_DISCOVERY_CONFIG') or DEFAULT_CONFIG)
    if not target.exists():
        return {'enabled': False, 'queries': [], 'config_path': str(target), 'missing': True,
                'issues': []}
    try:
        raw = json.loads(target.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        return {'enabled': False, 'queries': [], 'config_path': str(target),
                'issues': [{'severity': 'error', 'code': 'discovery_config_invalid',
                            'message': f'{type(exc).__name__}: {exc}'}]}
    if not isinstance(raw, dict):
        return {'enabled': False, 'queries': [], 'config_path': str(target),
                'issues': [{'severity': 'error', 'code': 'discovery_config_invalid',
                            'message': 'config must be a JSON object'}]}
    config = dict(raw)
    env_flag = os.environ.get('OR_DISCOVERY_ENABLED', '').strip().lower() in {'1','true','yes','on'}
    config['enabled'] = bool(raw.get('enabled')) and env_flag
    config['config_path'] = str(target)
    config['missing'] = False
    config.setdefault('max_items_per_query', 8)
    config.setdefault('max_pages_per_run', 6)
    config.setdefault('page_fetch', True)
    config.setdefault('max_age_days', 7)
    config.setdefault('max_summary_chars', 6000)
    queries = raw.get('queries') if isinstance(raw.get('queries'), list) else []
    config['queries'] = [q for q in queries if isinstance(q, dict)]
    issues = list(config.get('issues') or [])
    for query in config['queries']:
        issues.extend(_validate_query(query))
    config['issues'] = issues
    return config


def _validate_query(query: dict) -> list[dict]:
    issues = []
    qid = str(query.get('query_id') or '').strip()
    if not qid:
        issues.append({'severity': 'error', 'code': 'discovery_missing_query_id',
                       'message': 'query_id is required'})
    if not str(query.get('query') or '').strip():
        issues.append({'severity': 'error', 'code': 'discovery_missing_query',
                       'message': f'{qid or "(unknown)"}: query is required', 'source_id': qid})
    provider = str(query.get('provider') or '')
    if provider not in {'google_news', 'gdelt', 'newsapi', 'brave', 'guardian'}:
        issues.append({'severity': 'error', 'code': 'discovery_invalid_provider',
                       'message': f'{qid}: provider must be google_news, gdelt, newsapi, brave or guardian',
                       'source_id': qid})
    if provider == 'brave' and not os.environ.get('OR_BRAVE_API_KEY'):
        issues.append({'severity': 'warning', 'code': 'discovery_missing_key',
                       'message': f'{qid}: OR_BRAVE_API_KEY is not set', 'source_id': qid})
    if provider == 'newsapi' and not os.environ.get('OR_NEWSAPI_KEY'):
        issues.append({'severity': 'warning', 'code': 'discovery_missing_key',
                       'message': f'{qid}: OR_NEWSAPI_KEY is not set', 'source_id': qid})
    if provider == 'guardian' and not os.environ.get('OR_GUARDIAN_API_KEY'):
        issues.append({'severity': 'warning', 'code': 'discovery_missing_key',
                       'message': f'{qid}: OR_GUARDIAN_API_KEY is not set', 'source_id': qid})
    if query.get('enabled') and str(query.get('permission_status') or '') != 'approved':
        issues.append({'severity': 'error', 'code': 'discovery_not_approved',
                       'message': f'{qid}: enabled queries must have permission_status=approved',
                       'source_id': qid})
    return issues


def enabled_queries(config: dict) -> list[dict]:
    if not config.get('enabled'):
        return []
    return [q for q in config.get('queries') or []
            if q.get('enabled') and str(q.get('permission_status') or '') == 'approved']


def source_objects(config: dict) -> list[Source]:
    out = []
    for q in enabled_queries(config):
        qid = str(q.get('query_id') or '')
        if not qid:
            continue
        provider = str(q.get('provider') or '')
        url = {'google_news': 'https://news.google.com/', 'gdelt': 'https://www.gdeltproject.org/',
               'newsapi': 'https://newsapi.org/', 'brave': 'https://brave.com/search/api/',
               'guardian': 'https://www.theguardian.com/'}.get(provider, 'https://example.invalid/')
        out.append(Source(
            source_id=f'search:{qid}', name=str(q.get('name') or qid), homepage=url, feed_url=url,
            access_method='official_api' if provider != 'google_news' else 'rss',
            permission_status='approved', enabled=True, freshrss_feed_id='', source_type='search',
            provenance_class='secondhand_report', canonical_domain=urllib.parse.urlparse(url).hostname or '',
            terms_url=str(q.get('terms_url') or _provider_terms(provider)),
            last_verified_at=str(q.get('last_verified_at') or ''),
            reviewed_at=str(q.get('reviewed_at') or ''),
            editorial_lanes=str(q.get('editorial_lanes') or 'A,B,C'),
            topic_tags=str(q.get('topic_tags') or ''),
            source_authority=str(q.get('source_authority') or ''),
            content_access_level='excerpt', source_cap=_cap(q.get('source_cap', 2)),
            intelligence_lines=str(q.get('intelligence_lines') or 'market'),
            full_text_fetch='none'))
    return out


def _provider_terms(provider: str) -> str:
    return {'google_news': 'https://news.google.com/',
            'gdelt': 'https://www.gdeltproject.org/about.html#termsofuse',
            'newsapi': 'https://newsapi.org/terms',
            'brave': 'https://brave.com/search/api/',
            'guardian': 'https://www.theguardian.com/help/terms-of-service'}.get(provider, '')


def _cap(value) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _get_text(http: Http, url: str, headers: dict | None = None) -> str:
    return http.get_text(url, headers)


def _json(http: Http, url: str, headers: dict | None = None) -> dict:
    return http.get_json(url, headers)


def _clean(text) -> str:
    return SPACE.sub(' ', html.unescape(TAG.sub(' ', str(text or '')))).strip()


def _parse_date(value) -> str:
    if not value:
        return ''
    text = str(value).strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        return text
    if re.fullmatch(r'\d{8}T\d{6}Z?', text):
        return f'{text[:4]}-{text[4:6]}-{text[6:8]}'
    try:
        return parsedate_to_datetime(text).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00')).date().isoformat()
    except ValueError:
        return ''


def _recent(published: str, max_age_days: int) -> bool:
    if not published:
        return True
    try:
        return (datetime.now(timezone.utc).date() - datetime.fromisoformat(published).date()).days <= max_age_days
    except ValueError:
        return True


def _query_params(query: dict) -> str:
    base = str(query.get('query') or '').strip()
    extra = []
    if query.get('language') and query.get('provider') == 'gdelt':
        extra.append(f"sourcelang:{query['language']}")
    if query.get('country') and query.get('provider') == 'gdelt':
        extra.append(f"sourcecountry:{query['country']}")
    return ' '.join([base] + extra).strip()


def fetch_google_news(query: dict, http: Http) -> list[dict]:
    params = {'q': _query_params(query), 'hl': query.get('hl') or 'en-US',
              'gl': query.get('gl') or 'US', 'ceid': query.get('ceid') or 'US:en'}
    url = GOOGLE_NEWS + '?' + urllib.parse.urlencode(params)
    xml_text = _get_text(http, url)
    root = ET.fromstring(xml_text)
    out = []
    for item in root.findall('.//item'):
        title = _clean(item.findtext('title'))
        link = (item.findtext('link') or '').strip()
        if not title or not link:
            continue
        source = item.find('source')
        publisher = _clean(source.text if source is not None else '')
        out.append({'title': title, 'url': link, 'published': _parse_date(item.findtext('pubDate')),
                    'publisher': publisher or urllib.parse.urlparse(link).hostname or '',
                    'summary': '', 'provider': 'google_news'})
    return out


def fetch_gdelt(query: dict, http: Http) -> list[dict]:
    global _last_gdelt
    wait = GDELT_MIN_INTERVAL - (time.monotonic() - _last_gdelt)
    if wait > 0:
        time.sleep(wait)
    params = {'query': _query_params(query), 'mode': 'artlist', 'format': 'json',
              'maxrecords': str(int(query.get('max_items') or 20)),
              'timespan': f"{int(query.get('timespan_days') or 3)}d", 'sort': 'hybridrel'}
    url = GDELT + '?' + urllib.parse.urlencode(params)
    data = None
    try:
        for attempt in range(2):
            try:
                data = _json(http, url)
                break
            except DiscoveryUnavailable as exc:
                if '429' in str(exc) and attempt == 0:
                    time.sleep(GDELT_MIN_INTERVAL * 2)
                    continue
                raise
    finally:
        _last_gdelt = time.monotonic()
    if data is None:
        raise DiscoveryUnavailable('GDELT did not return a payload')
    out = []
    for item in data.get('articles') or []:
        if not isinstance(item, dict):
            continue
        link = str(item.get('url') or '').strip()
        title = _clean(item.get('title'))
        if not title or not link:
            continue
        out.append({'title': title, 'url': link, 'published': _parse_date(item.get('seendate')),
                    'publisher': str(item.get('domain') or ''),
                    'summary': '', 'provider': 'gdelt',
                    'country': item.get('sourcecountry') or '', 'language': item.get('language') or ''})
    return out


def fetch_newsapi(query: dict, http: Http) -> list[dict]:
    key = os.environ.get('OR_NEWSAPI_KEY', '').strip()
    if not key:
        raise DiscoveryUnavailable('OR_NEWSAPI_KEY is not configured')
    params = {'q': _query_params(query), 'language': query.get('language') or 'en',
              'sortBy': 'publishedAt', 'pageSize': str(int(query.get('max_items') or 20))}
    url = NEWSAPI + '?' + urllib.parse.urlencode(params)
    data = _json(http, url, {'X-Api-Key': key})
    out = []
    for item in data.get('articles') or []:
        if not isinstance(item, dict):
            continue
        out.append({'title': _clean(item.get('title')), 'url': str(item.get('url') or ''),
                    'published': _parse_date(item.get('publishedAt')),
                    'publisher': _clean((item.get('source') or {}).get('name')),
                    'summary': _clean(item.get('description') or ''), 'provider': 'newsapi'})
    return out


def fetch_brave(query: dict, http: Http) -> list[dict]:
    key = os.environ.get('OR_BRAVE_API_KEY', '').strip()
    if not key:
        raise DiscoveryUnavailable('OR_BRAVE_API_KEY is not configured')
    params = {'q': _query_params(query), 'count': str(int(query.get('max_items') or 20)),
              'freshness': f"{int(query.get('freshness_days') or 7)}d"}
    url = BRAVE + '?' + urllib.parse.urlencode(params)
    data = _json(http, url, {'X-Subscription-Token': key, 'Accept': 'application/json'})
    out = []
    for item in data.get('results') or []:
        if not isinstance(item, dict):
            continue
        out.append({'title': _clean(item.get('title')), 'url': str(item.get('url') or ''),
                    'published': _parse_date(item.get('page_age') or item.get('age')),
                    'publisher': _clean((item.get('meta_url') or {}).get('hostname') or ''),
                    'summary': _clean(item.get('description') or ''), 'provider': 'brave'})
    return out


def fetch_guardian(query: dict, http: Http) -> list[dict]:
    key = os.environ.get('OR_GUARDIAN_API_KEY', '').strip()
    if not key:
        raise DiscoveryUnavailable('OR_GUARDIAN_API_KEY is not configured')
    params = {'q': query.get('query'), 'api-key': key, 'page-size': str(int(query.get('max_items') or 20)),
              'show-fields': 'trailText,headline', 'order-by': 'newest'}
    url = GUARDIAN + '?' + urllib.parse.urlencode(params)
    data = _json(http, url)
    out = []
    for item in ((data.get('response') or {}).get('results') or []):
        if not isinstance(item, dict):
            continue
        fields = item.get('fields') or {}
        out.append({'title': _clean(fields.get('headline') or item.get('webTitle')),
                    'url': str(item.get('webUrl') or ''), 'published': _parse_date(item.get('webPublicationDate')),
                    'publisher': 'The Guardian', 'summary': _clean(fields.get('trailText') or ''),
                    'provider': 'guardian'})
    return out


PROVIDERS = {'google_news': fetch_google_news, 'gdelt': fetch_gdelt, 'newsapi': fetch_newsapi,
             'brave': fetch_brave, 'guardian': fetch_guardian}


def _hostname(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or '').lower().removeprefix('www.')


def _summary(query: dict, item: dict, page: dict | None, max_chars: int) -> str:
    header = (f"[公开检索] {item.get('provider','')} | {query.get('name') or query.get('query_id')} | "
              f"{item.get('publisher','') or _hostname(item.get('url',''))} | {item.get('published','') or 'date unknown'}")
    snippet = _clean(item.get('summary') or '')
    if page and page.get('ok'):
        body = str(page.get('text') or '')
        return header + ' | page fetched\n\n' + body[:max_chars]
    if len(snippet) >= 80:
        return header + '\n\n' + snippet[:max_chars]
    context = ' '.join(x for x in (item.get('title'), snippet) if x).strip()
    return header + '\n\n' + context


def collect(config: dict, store=None, http: Http | None = None,
            page_fetcher=None) -> tuple[list[DiscoveryArticle], dict, list[dict]]:
    http = http or Http()
    counters = {'queries': 0, 'candidates': 0, 'selected': 0, 'page_fetched': 0,
                'page_skipped': 0, 'skipped_seen': 0, 'skipped_reason': {},
                'providers': {}, 'pages_left': int(config.get('max_pages_per_run', 6))}
    issues = list(config.get('issues') or [])
    articles = []
    if not config.get('enabled'):
        return articles, counters, issues
    seen_urls = set(); seen_titles = set()
    budget = int(config.get('max_items_per_query', 8))
    for query in enabled_queries(config):
        counters['queries'] += 1
        qid = str(query.get('query_id') or '')
        provider = str(query.get('provider') or '')
        fetch = PROVIDERS.get(provider)
        if fetch is None:
            continue
        try:
            results = fetch(query, http)
        except DiscoveryUnavailable as exc:
            issues.append({'severity': 'warning', 'code': 'discovery_fetch_failed',
                           'source_id': qid, 'message': str(exc)[:500]})
            continue
        counters['providers'][provider] = counters['providers'].get(provider, 0) + len(results)
        per_query = 0
        for item in results:
            counters['candidates'] += 1
            if per_query >= min(budget, int(query.get('max_items') or budget)):
                break
            url = str(item.get('url') or '').strip()
            title = str(item.get('title') or '').strip()
            if not url.startswith('https://') or not title:
                counters['skipped_reason']['invalid'] = counters['skipped_reason'].get('invalid', 0) + 1
                continue
            keywords = [str(k).lower() for k in query.get('keywords') or [] if str(k).strip()]
            if keywords and not any(k in title.lower() for k in keywords):
                counters['skipped_reason']['title_keywords'] = counters['skipped_reason'].get('title_keywords', 0) + 1
                continue
            key = hashlib.sha256(url.encode()).hexdigest()
            publisher = str(item.get('publisher') or _hostname(url))
            title_key = publisher.lower() + '|' + re.sub(r'\W+', ' ', title.lower()).strip()
            if key in seen_urls or title_key in seen_titles:
                counters['skipped_reason']['duplicate'] = counters['skipped_reason'].get('duplicate', 0) + 1
                continue
            published = str(item.get('published') or '')
            if not _recent(published, int(config.get('max_age_days', 7))):
                counters['skipped_reason']['too_old'] = counters['skipped_reason'].get('too_old', 0) + 1
                continue
            if store is not None and store.article_exists(key):
                counters['skipped_seen'] += 1; continue
            seen_urls.add(key); seen_titles.add(title_key)
            page = None
            if config.get('page_fetch', True) and query.get('fetch_pages', provider == 'gdelt'):
                if counters['pages_left'] <= 0:
                    counters['page_skipped'] += 1
                else:
                    fetcher = page_fetcher or FullTextFetcher(max_chars=int(config.get('max_summary_chars', 6000)))
                    page = fetcher.fetch(url)
                    counters['pages_left'] -= 1
                    if page.get('ok'):
                        counters['page_fetched'] += 1
                    else:
                        counters['page_skipped'] += 1
                        counters['skipped_reason'][page.get('status') or 'page_failed'] = \
                            counters['skipped_reason'].get(page.get('status') or 'page_failed', 0) + 1
            summary = _summary(query, item, page, int(config.get('max_summary_chars', 6000)))
            article = DiscoveryArticle(
                article_id=key[:16], title=title, url=url, summary=summary, published=published,
                source_name=str(item.get('publisher') or _hostname(url) or provider), feed_id='',
                source_id=f'search:{qid}', fetched_at=datetime.now(timezone.utc).isoformat(),
                content_source='article_page' if page and page.get('ok') else 'search_snippet',
                retrieval_status='ok' if page and page.get('ok') else 'snippet_only',
                discovery={'provider': provider, 'query_id': qid,
                           'query': str(query.get('query') or ''),
                           'publisher': str(item.get('publisher') or _hostname(url)),
                           'page_status': (page or {}).get('status', 'not_attempted'),
                           'page_container': (page or {}).get('container', ''),
                           'snippet_chars': len(_clean(item.get('summary') or '')),
                           'country': item.get('country') or query.get('country') or '',
                           'language': item.get('language') or query.get('language') or ''})
            articles.append(article)
            counters['selected'] += 1
            per_query += 1
    counters['fetched'] = len(articles)
    return articles, counters, issues


def explain(query: str, provider: str = 'google_news', http: Http | None = None) -> dict:
    """Operator check for one ad-hoc query; no storage, no analysis."""
    query = {'query_id': 'ad-hoc', 'name': query, 'provider': provider, 'query': query,
             'max_items': 5, 'permission_status': 'approved', 'enabled': True}
    fetch = PROVIDERS.get(provider)
    if fetch is None:
        raise DiscoveryUnavailable(f'unknown provider: {provider}')
    results = fetch(query, http or Http())
    return {'provider': provider, 'query': query, 'count': len(results),
            'results': results[:5]}
