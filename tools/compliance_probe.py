"""Probe candidate sources for the 2026-11-08 compliance review.

Reads config/sources.local.csv (machine-local, gitignored) and, for every candidate,
records what a reviewer needs before approving it:

  * does the feed URL answer, with what content type and how many items;
  * what does robots.txt say about the feed path;
  * does the terms URL answer (the text itself is for a human to read).

It writes reports/compliance/<date>.json and prints a table. It never changes the
registry: approval is a human decision recorded in docs/SOURCE_COMPLIANCE_REVIEW_<date>.md.

Run: python tools/compliance_probe.py [source_id ...]
"""
import csv
import gzip
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

UA = 'OpportunityRadar/0.1 (personal research digest; one request per source)'
PROXY = {'http': 'http://127.0.0.1:7890', 'https': 'http://127.0.0.1:7890'}


def get(url, timeout=25, limit=400_000):
    """Direct first, then the local proxy. Returns (status, headers, body_bytes, via)."""
    errors = []
    for via, opener in (('direct', urllib.request.build_opener(urllib.request.ProxyHandler({}))),
                        ('proxy', urllib.request.build_opener(urllib.request.ProxyHandler(PROXY)))):
        request = urllib.request.Request(url, headers={'User-Agent': UA,
                                                       'Accept': '*/*'})
        try:
            with opener.open(request, timeout=timeout) as response:
                body = response.read(limit)
                if response.headers.get('Content-Encoding') == 'gzip':
                    try:
                        body = gzip.decompress(body)
                    except OSError:
                        pass
                return response.status, dict(response.headers), body, via
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers or {}), b'', via
        except Exception as exc:  # noqa: BLE001 - recorded, not raised
            errors.append(f'{via}:{type(exc).__name__}')
    return 0, {}, b'', ','.join(errors)


def robots_for(host_scheme):
    status, _, body, via = get(host_scheme.rstrip('/') + '/robots.txt')
    return status, body.decode('utf-8', 'replace'), via


def robots_verdict(text, path, agent='*'):
    """Longest-match Allow/Disallow for our agent, restricted to the feed path."""
    if not text.strip():
        return 'no robots.txt (allow)'
    groups = re.split(r'(?im)^\s*user-agent\s*:', text)
    rules = []
    for chunk in groups[1:]:
        lines = chunk.splitlines()
        name = lines[0].strip().lower()
        if name not in ('*', 'opportunityradar'):
            continue
        current_allow = False
        for line in lines[1:]:
            match = re.match(r'(?i)^\s*(allow|disallow)\s*:\s*(\S*)', line)
            if match:
                current_allow = match.group(1).lower() == 'allow'
                pattern = match.group(2)
                if pattern:
                    rules.append((len(pattern), current_allow, pattern))
    best = None
    for length, allow, pattern in rules:
        if pattern == '/' or path.startswith(pattern.rstrip('*')):
            if best is None or length > best[0]:
                best = (length, allow, pattern)
    if best is None:
        return 'allowed (no matching rule)'
    return ('allowed by ' if best[1] else 'DISALLOWED by ') + f'{best[2]}'


def count_items(body):
    text = body.decode('utf-8', 'replace')
    items = len(re.findall(r'<item[\s>]', text, re.I))
    entries = len(re.findall(r'<entry[\s>]', text, re.I))
    return items or entries, text[:400]


def main(argv):
    wanted = set(argv[1:])
    rows = list(csv.DictReader(io.open('config/sources.local.csv', encoding='utf-8-sig', newline='')))
    candidates = [r for r in rows if r.get('feed_url', '').startswith('https://')
                  and (not wanted or r['source_id'] in wanted)]
    cache = {}
    out = []
    for row in candidates:
        feed = row['feed_url']
        host = urllib.parse.urlsplit(feed)
        base = f'{host.scheme}://{host.netloc}'
        status, headers, body, via = get(feed)
        items, head = count_items(body) if body else (0, '')
        if base not in cache:
            cache[base] = robots_for(base)
            time.sleep(1)
        robots_status, robots_text, robots_via = cache[base]
        record = {
            'source_id': row['source_id'],
            'name': row['name'],
            'permission_status': row['permission_status'],
            'feed_url': feed,
            'feed_status': status,
            'feed_type': headers.get('Content-Type', ''),
            'feed_items': items,
            'feed_head': head[:160],
            'via': via,
            'robots_status': robots_status,
            'robots_verdict': robots_verdict(robots_text, host.path),
            'terms_url': row.get('terms_url', ''),
            'homepage': row.get('homepage', ''),
            'intelligence_lines': row.get('intelligence_lines', ''),
        }
        out.append(record)
        print(f"{row['source_id']:24} {status:>3} items={items:<3} {record['robots_verdict'][:48]:50} {row['name'][:30]}")
        time.sleep(1)

    target = Path('reports') / 'compliance' / f'{date.today().isoformat()}.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n{len(out)} sources probed -> {target}')


if __name__ == '__main__':
    main(sys.argv)
