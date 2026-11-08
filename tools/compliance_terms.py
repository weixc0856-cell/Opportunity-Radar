"""Fetch the terms pages a source review needs, and pull the clauses that matter.

Saving the page text keeps the review auditable: every verdict in
docs/SOURCE_COMPLIANCE_REVIEW_<date>.md points at a file under reports/compliance/terms/.

Run: python tools/compliance_terms.py [source_id ...]
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

UA = 'OpportunityRadar/0.1 (personal research digest)'
PROXY = {'http': 'http://127.0.0.1:7890', 'https': 'http://127.0.0.1:7890'}
KEYWORDS = ('rss', 'feed', 'syndicat', 'redistribut', 'reproduc', 'commercial use',
            'non-commercial', 'scrap', 'crawl', 'automat', 'robot', 'copy', 'licen',
            'personal use', 'attribution', 'aggregat')


def get(url, timeout=30):
    for opener in (urllib.request.build_opener(urllib.request.ProxyHandler({})),
                   urllib.request.build_opener(urllib.request.ProxyHandler(PROXY))):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': UA})
            with opener.open(request, timeout=timeout) as response:
                return response.status, response.read(900_000).decode('utf-8', 'replace')
        except urllib.error.HTTPError as exc:
            return exc.code, ''
        except Exception:  # noqa: BLE001
            continue
    return 0, ''


def text_of(html):
    html = re.sub(r'(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>', ' ', html)
    html = re.sub(r'(?s)<[^>]+>', ' ', html)
    html = re.sub(r'&nbsp;', ' ', html)
    html = re.sub(r'&amp;', '&', html)
    return re.sub(r'\s+', ' ', html)


def main(argv):
    wanted = set(argv[1:])
    rows = json.load(open('reports/compliance/2026-11-08.json', encoding='utf-8'))
    outdir = Path('reports') / 'compliance' / 'terms'
    outdir.mkdir(parents=True, exist_ok=True)
    summary = []
    seen = set()
    for row in rows:
        if wanted and row['source_id'] not in wanted:
            continue
        url = row.get('terms_url') or ''
        if not url or url in seen:
            continue
        seen.add(url)
        status, html = get(url)
        text = text_of(html) if html else ''
        path = outdir / f"{row['source_id']}.txt"
        path.write_text(f"URL: {url}\nSTATUS: {status}\n\n{text}", encoding='utf-8')
        hits = []
        for sentence in re.split(r'(?<=[.!?。])\s+', text):
            low = sentence.lower()
            if any(k in low for k in KEYWORDS) and 40 <= len(sentence) <= 400:
                hits.append(sentence.strip())
        summary.append({'source_id': row['source_id'], 'terms_url': url, 'status': status,
                        'chars': len(text), 'file': str(path), 'hits': hits[:12]})
        print(f"{row['source_id']:22} {status:>3} {len(text):>7} chars  {len(hits):>2} matching sentences")
        time.sleep(1)
    Path('reports/compliance/terms-summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n{len(summary)} terms pages -> reports/compliance/terms/')


if __name__ == '__main__':
    main(sys.argv)
