"""HTTP transport, rate limiting and the failure taxonomy for the ingest channel.

The taxonomy matches the acceptance criteria in
docs/archive/FAILURE_INJECTION_ACCEPTANCE_2026-11-01.md §3:
auth / rate_limit / not_found / server / timeout / schema / truncation / empty_result / rights.
"""
from __future__ import annotations
import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

AUTH = 'auth'
RATE_LIMIT = 'rate_limit'
NOT_FOUND = 'not_found'
SERVER = 'server'
TIMEOUT = 'timeout'
SCHEMA = 'schema'
TRUNCATION = 'truncation'
EMPTY_RESULT = 'empty_result'
RIGHTS = 'rights'

ALL_CLASSES = (AUTH, RATE_LIMIT, NOT_FOUND, SERVER, TIMEOUT, SCHEMA, TRUNCATION, EMPTY_RESULT, RIGHTS)


class IngestError(Exception):
    def __init__(self, error_class, detail, status=None, retryable=False):
        super().__init__(f'{error_class}: {detail}')
        self.error_class = error_class
        self.detail = detail
        self.status = status
        self.retryable = retryable


@dataclass
class Response:
    status: int
    body: bytes = b''
    headers: dict = field(default_factory=dict)

    def json(self):
        try:
            return json.loads(self.body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError) as exc:
            raise IngestError(SCHEMA, f'response is not JSON: {exc}', self.status) from exc


def _decompress(body, encoding):
    """urllib does not decode Content-Encoding; a gzip body would otherwise look like garbage."""
    encoding = (encoding or '').lower().strip()
    if not encoding or encoding == 'identity':
        return body
    try:
        if encoding == 'gzip':
            import gzip
            return gzip.decompress(body)
        if encoding == 'deflate':
            import zlib
            try:
                return zlib.decompress(body)
            except zlib.error:
                return zlib.decompress(body, -zlib.MAX_WBITS)
    except Exception as exc:  # noqa: BLE001 - a broken body is a schema error, not a crash
        raise IngestError(SCHEMA, f'could not decode {encoding} body: {exc}') from exc
    return body


class UrllibTransport:
    """Default transport. Headers are set by the caller so no secret leaks here."""

    def get(self, url, headers=None, timeout=30):
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                hdrs = dict(r.headers)
                return Response(r.status, _decompress(raw, hdrs.get('Content-Encoding')), hdrs)
        except urllib.error.HTTPError as exc:
            return Response(exc.code, exc.read() if hasattr(exc, 'read') else b'')
        except (socket.timeout, TimeoutError) as exc:
            raise IngestError(TIMEOUT, f'socket timeout: {exc}') from exc
        except urllib.error.URLError as exc:
            if isinstance(getattr(exc, 'reason', None), (socket.timeout, TimeoutError)):
                raise IngestError(TIMEOUT, f'socket timeout: {exc.reason}') from exc
            raise IngestError(SERVER, f'transport error: {exc.reason}') from exc


class RateLimiter:
    """Client-side floor between requests; the caller sets the interval."""

    def __init__(self, max_rps, clock=time.monotonic, sleep=time.sleep):
        self.min_interval = 0.0 if max_rps <= 0 else 1.0 / float(max_rps)
        self._clock = clock
        self._sleep = sleep
        self._last = None

    def wait(self):
        if self.min_interval <= 0:
            return
        now = self._clock()
        if self._last is not None:
            delay = self.min_interval - (now - self._last)
            if delay > 0:
                self._sleep(delay)
                now = self._clock()
        self._last = now


def classify(status):
    if status in (401, 403):
        return AUTH
    if status == 429:
        return RATE_LIMIT
    if status == 404:
        return NOT_FOUND
    if 500 <= status <= 599:
        return SERVER
    return None


RETRYABLE = {RATE_LIMIT, SERVER, TIMEOUT}


def get_json(transport, url, headers=None, timeout=30, limiter=None,
             attempts=3, base_delay=0.5, sleep=time.sleep):
    """GET with bounded retries. Never retries auth/not_found; never loops forever."""
    last = None
    for attempt in range(attempts):
        if limiter:
            limiter.wait()
        try:
            resp = transport.get(url, headers=headers, timeout=timeout)
        except IngestError as exc:
            last = exc
            if not exc.retryable and exc.error_class != TIMEOUT:
                raise
            if attempt == attempts - 1:
                raise
            sleep(base_delay * (2 ** attempt))
            continue
        cls = classify(resp.status)
        if cls:
            err = IngestError(cls, f'HTTP {resp.status}', resp.status, retryable=cls in RETRYABLE)
            if not err.retryable or attempt == attempts - 1:
                raise err
            last = err
            sleep(base_delay * (2 ** attempt))
            continue
        return resp.json()
    raise last or IngestError(SERVER, 'exhausted retries')
