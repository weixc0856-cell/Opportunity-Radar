#!/usr/bin/env python3
"""Add the `intelligence_lines` column to an existing source registry.

The parser treats a missing column as "undeclared" and the audit reports it, so an old
registry keeps working. This tool makes the migration explicit: it appends the column and
fills only the rows whose source_id appears in DEFAULT_MAP. Anything else is left blank
and listed, rather than guessed from the source name.

Usage:
    python tools/migrate_intelligence_lines.py config/sources.local.csv
    python tools/migrate_intelligence_lines.py config/sources.local.csv --dry-run
"""
import argparse
import csv
import io
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opportunity_radar.intelligence_lines import (  # noqa: E402
    CORP, ENGINEERING, INDUSTRY, MACRO, NEWS, OPPORTUNITY, POLICY, TECH,
)

# Declared per source_id. Derived from the source's stated purpose, not from its name.
DEFAULT_MAP = {
    'openai-news': TECH,
    'deepmind-blog': TECH,
    'huggingface-blog': TECH,
    'google-ai-blog': TECH,
    'arxiv-cs-ai': TECH,
    'arxiv-cs-lg': TECH,
    'techcrunch-ai': f'{NEWS},{TECH}',
    'simon-willison': TECH,
    'github-blog': TECH,
    'simscale-blog': f'{TECH},{ENGINEERING}',
    'hackernews-front': TECH,
    'hn-ask': f'{OPPORTUNITY},{TECH}',
    'hn-show': f'{OPPORTUNITY},{TECH}',
    'precice-forum': ENGINEERING,
    'paraview-forum': ENGINEERING,
    'salome-forum': ENGINEERING,
    'openai-community': f'{OPPORTUNITY},{TECH}',
    'simscale-forum': ENGINEERING,
    'nvidia-newsroom': CORP,
    'nvidia-ir': CORP,
    'microsoft-blog': f'{CORP},{TECH}',
    'microsoft-research': TECH,
    'amd-ir': CORP,
    'google-research': TECH,
    'aws-ml-blog': TECH,
    'imf-publications': MACRO,
    'oecd-publications': MACRO,
    'world-bank-research': MACRO,
    'sia-news': INDUSTRY,
    'mit-tech-review': f'{NEWS},{TECH}',
    'ieee-spectrum': f'{INDUSTRY},{TECH}',
    # Verified official and news sources added 2026-10-23 (see docs/SOURCE_REVIEW.md).
    'cn-pbc': POLICY,
    'us-bea': MACRO,
    'us-bls': MACRO,
    'us-bls-weekly': MACRO,
    'us-census': MACRO,
    'us-fed': MACRO,
    'uk-ons': MACRO,
    'bbc-news': NEWS,
    'nyt-home': NEWS,
}


def migrate(path: Path, dry_run: bool = False) -> dict:
    raw = path.read_bytes()
    bom = raw.startswith(b'\xef\xbb\xbf')
    crlf = b'\r\n' in raw
    text = raw.decode('utf-8-sig')
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise SystemExit(f'No rows in {path}')
    fields = list(rows[0].keys())
    added = 'intelligence_lines' not in fields
    if added:
        fields.append('intelligence_lines')

    filled, skipped, already = [], [], []
    for row in rows:
        sid = (row.get('source_id') or '').strip()
        current = (row.get('intelligence_lines') or '').strip()
        if current and not added:
            already.append(sid)
            continue
        proposed = DEFAULT_MAP.get(sid, '')
        row['intelligence_lines'] = current or proposed
        if proposed and not current:
            filled.append(sid)
        elif not current:
            skipped.append(sid)

    if dry_run:
        return {'added_column': added, 'filled': filled, 'skipped': skipped,
                'already': already, 'path': str(path)}

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction='ignore',
                            lineterminator='\r\n' if crlf else '\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, '') or '' for k in fields})
    body = buf.getvalue()
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(body, encoding='utf-8-sig' if bom else 'utf-8', newline='')
    os.replace(tmp, path)
    return {'added_column': added, 'filled': filled, 'skipped': skipped,
            'already': already, 'path': str(path)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('registry', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    result = migrate(args.registry, args.dry_run)
    verb = 'would add' if args.dry_run else 'added'
    if result['added_column']:
        print(f"{verb} column 'intelligence_lines' to {result['path']}")
    print(f"Filled: {len(result['filled'])} -> {', '.join(result['filled']) or '(none)'}")
    print(f"Preexisting values kept: {len(result['already'])}")
    if result['skipped']:
        print("Left undeclared (assign a line before relying on the report): "
              + ', '.join(result['skipped']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
