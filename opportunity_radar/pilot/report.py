"""Run summaries for the source pilot. Runtime reports, not product documentation."""
from __future__ import annotations

import json
from pathlib import Path


def _top_domains(store, limit=20):
    with store.connect() as conn:
        rows = conn.execute(
            'SELECT domain, COUNT(*) AS n FROM discovery_candidates '
            'GROUP BY domain ORDER BY n DESC, domain LIMIT ?', (limit,)
        ).fetchall()
    return [{'domain': row['domain'], 'candidates': row['n']} for row in rows]


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(text, encoding='utf-8')
    temp.replace(path)


def write_gdelt_summary(store, run_id, settings, summary):
    directory = Path(settings.report_dir) / 'gdelt' / str(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    payload = dict(summary)
    payload['top_domains'] = _top_domains(store)
    payload['failures'] = store.failures(run_id)
    _write(directory / 'summary.json',
           json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    lines = [
        f"# GDELT pilot run {run_id}",
        '',
        f"- status: `{summary.get('status')}`",
        f"- requests: {summary.get('requests')}",
        f"- candidate observations: {summary.get('candidate_observations')}",
        f"- unique candidates: {summary.get('unique_candidates')}",
        f"- duplicates in production: {summary.get('duplicates')}",
        f"- invalid URLs: {summary.get('invalid')}",
        f"- errors: {summary.get('errors')}",
        f"- seconds: {summary.get('seconds')}",
        f"- production index available: {summary.get('production_index_available')}",
        '',
        '## Resolution counts',
        '',
    ]
    for key, value in sorted((summary.get('resolution_counts') or {}).items()):
        lines.append(f'- `{key}`: {value}')
    lines.extend(['', '## Queries', ''])
    for query in summary.get('queries') or []:
        lines.append(
            f"- `{query.get('query_id')}`: {query.get('status')} "
            f"articles={query.get('articles', 0)} accepted={query.get('accepted', 0)}"
        )
    lines.extend(['', '## HTTP requests', ''])
    for request in summary.get('requests_log') or []:
        lines.append(
            f"- `{request.get('query_id')}` {request.get('requested_at')} "
            f"status={request.get('status')} bytes={request.get('body_bytes')} "
            f"url={request.get('url')}"
        )
        preview = (request.get('body_preview') or '').replace('\n', ' ')[:200]
        if preview:
            lines.append(f"  - body: `{preview}`")
    lines.extend(['', '## Top domains', ''])
    for item in payload['top_domains']:
        lines.append(f"- `{item['domain']}`: {item['candidates']}")
    if payload['failures']:
        lines.extend(['', '## Failures', ''])
        for failure in payload['failures']:
            label = failure.get('external_ref') or failure.get('query_id') or '-'
            lines.append(
                f"- `{label}` {failure.get('error_class')}: {failure.get('detail')}"
            )
    _write(directory / 'summary.md', '\n'.join(lines) + '\n')
    return directory


def latest_summary(store, source_id='gdelt'):
    run = store.latest_run(source_id)
    if not run:
        return None
    with store.connect() as conn:
        failures = conn.execute(
            'SELECT COUNT(*) FROM pilot_failures WHERE run_id=?', (run['run_id'],)
        ).fetchone()[0]
    return {'run': run, 'failures': failures}


def _top_policy_agencies(store, limit=20):
    with store.connect() as conn:
        rows = conn.execute(
            'SELECT agency_slugs, COUNT(*) AS n FROM policy_documents '
            'WHERE agency_slugs<>"" GROUP BY agency_slugs ORDER BY n DESC, agency_slugs LIMIT ?',
            (limit,)
        ).fetchall()
    return [{'agency_slugs': row['agency_slugs'], 'documents': row['n']} for row in rows]


def write_federal_register_summary(store, run_id, settings, summary):
    directory = Path(settings.report_dir) / 'federal-register' / str(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    payload = dict(summary)
    payload['failures'] = store.failures(run_id)
    payload['top_agencies'] = _top_policy_agencies(store)
    _write(directory / 'summary.json',
           json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    lines = [
        f"# Federal Register pilot run {run_id}",
        '',
        f"- status: `{summary.get('status')}`",
        f"- since: {summary.get('since')}",
        f"- requests: {summary.get('requests')} / pages: {summary.get('pages')}",
        f"- documents: {summary.get('documents')}",
        f"- inserted: {summary.get('inserted')} updated: {summary.get('updated')} "
        f"unchanged: {summary.get('unchanged')}",
        f"- duplicates: {summary.get('duplicates')} invalid: {summary.get('invalid')} "
        f"errors: {summary.get('errors')}",
        f"- truncated: {summary.get('truncated')}",
        f"- versions: {summary.get('version_count')}",
        '',
        '## By type',
        '',
    ]
    for key, value in sorted((summary.get('by_type') or {}).items()):
        lines.append(f'- `{key}`: {value}')
    lines.extend(['', '## Watches', ''])
    for watch in summary.get('watches') or []:
        lines.append(
            f"- `{watch.get('watch_id')}`: {watch.get('status')} "
            f"documents={watch.get('documents', 0)} requests={watch.get('requests', 0)}"
        )
    lines.extend(['', '## HTTP requests', ''])
    for request in summary.get('requests_log') or []:
        lines.append(
            f"- `{request.get('watch_id')}` page={request.get('page')} "
            f"{request.get('requested_at')} status={request.get('status')} "
            f"bytes={request.get('body_bytes')} url={request.get('url')}"
        )
    if payload['failures']:
        lines.extend(['', '## Failures', ''])
        for failure in payload['failures']:
            label = failure.get('external_ref') or failure.get('run_id') or '-'
            lines.append(f"- `{label}` {failure.get('error_class')}: {failure.get('detail')}")
    _write(directory / 'summary.md', '\n'.join(lines) + '\n')
    return directory


def write_bls_summary(store, run_id, settings, summary):
    directory = Path(settings.report_dir) / 'bls' / str(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    payload = dict(summary)
    payload['failures'] = store.failures(run_id)
    _write(directory / 'summary.json',
           json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    lines = [
        f"# BLS pilot run {run_id}",
        '',
        f"- status: `{summary.get('status')}`",
        f"- years: {summary.get('start_year')}-{summary.get('end_year')}",
        f"- requests: {summary.get('requests')}",
        f"- series: {summary.get('series_count')}",
        f"- observations: {summary.get('observations')}",
        f"- inserted: {summary.get('inserted')} updated: {summary.get('updated')} "
        f"unchanged: {summary.get('unchanged')}",
        f"- missing series: {summary.get('missing_series')} "
        f"invalid: {summary.get('invalid')} errors: {summary.get('errors')}",
        f"- versions: {summary.get('version_count')}",
        '',
        '## By frequency',
        '',
    ]
    for key, value in sorted((summary.get('by_frequency') or {}).items()):
        lines.append(f'- `{key}`: {value}')
    lines.extend(['', '## Series', ''])
    for series in summary.get('series') or []:
        lines.append(
            f"- `{series.get('series_id')}`: {series.get('status')} "
            f"observations={series.get('observations', 0)} "
            f"inserted={series.get('inserted', 0)} updated={series.get('updated', 0)} "
            f"unchanged={series.get('unchanged', 0)} invalid={series.get('invalid', 0)}"
        )
    lines.extend(['', '## HTTP requests', ''])
    for request in summary.get('requests_log') or []:
        lines.append(
            f"- {request.get('requested_at')} status={request.get('status')} "
            f"bytes={request.get('body_bytes')} url={request.get('url')}"
        )
    if payload['failures']:
        lines.extend(['', '## Failures', ''])
        for failure in payload['failures']:
            label = failure.get('external_ref') or failure.get('run_id') or '-'
            lines.append(f"- `{label}` {failure.get('error_class')}: {failure.get('detail')}")
    _write(directory / 'summary.md', '\n'.join(lines) + '\n')
    return directory
