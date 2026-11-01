"""Shared helpers for the ingest tests. Not a test module (no test_ prefix)."""
import json
from pathlib import Path

from opportunity_radar.ingest.http import Response

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'data' / 'failure-fixtures-2026-11-01'
EIA_SAMPLE = ROOT / 'data' / 'eia-sample-2026-11-01'
SEC_SAMPLE = ROOT / 'data' / 'sec-sample-2026-11-01'


def have(path):
    return Path(path).exists()


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


class FakeTransport:
    """Replays a local handler; records every call so tests can assert request volume."""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def get(self, url, headers=None, timeout=30):
        self.calls.append((url, dict(headers or {})))
        return self.handler(url)


def json_response(payload, status=200):
    return Response(status, json.dumps(payload, ensure_ascii=False).encode('utf-8'))


def raw_response(body, status=200):
    raw = body.encode('utf-8') if isinstance(body, str) else body
    return Response(status, raw)


def eia_handler(fixtures_by_offset):
    """Return a handler that serves a page per `offset` query parameter."""
    def handler(url):
        offset = 0
        for part in url.split('?', 1)[-1].split('&'):
            if part.startswith('offset='):
                offset = int(part.split('=', 1)[1])
        payload = fixtures_by_offset.get(offset)
        if payload is None:
            return json_response({'response': {'total': '0', 'data': []}})
        if isinstance(payload, Response):
            return payload
        return json_response(payload)
    return handler
