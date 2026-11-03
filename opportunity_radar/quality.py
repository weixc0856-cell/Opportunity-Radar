"""R6 quality, benchmark and backtest measurements over the production database.

Every number here is computed from stored rows. A metric that cannot be measured from the
database is returned as `NOT_MEASURED` with the reason, never as a model self-assessment
and never as a zero that reads like success.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

RULES_VERSION = 'quality-v1'
DEFAULT_DB = Path('data/opportunity_radar.sqlite3')
DEFAULT_QUALITY_DB = Path('data/quality/quality.sqlite3')
DEFAULT_REPORT_DIR = Path('reports/quality')
BENCHMARK_SUMMARY = Path('data/claim-pipeline/benchmark-final/summary.json')

QUALITY_SCHEMA = '''
CREATE TABLE IF NOT EXISTS quality_runs(
  run_id TEXT PRIMARY KEY,
  measured_at TEXT NOT NULL,
  database TEXT NOT NULL,
  rules_version TEXT NOT NULL,
  metrics_json TEXT NOT NULL,
  backtest_json TEXT NOT NULL DEFAULT '{}',
  benchmark_json TEXT NOT NULL DEFAULT '{}'
);
'''


def _connect(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _scalar(conn, sql, args=()):
    return conn.execute(sql, args).fetchone()[0]


def _pct(numerator, denominator):
    return round(100.0 * numerator / denominator, 2) if denominator else None


def _not_measured(reason):
    return {'status': 'NOT_MEASURED', 'reason': reason}


def metrics(db_path=DEFAULT_DB):
    """Point-in-time quality metrics derived from the stored event/evidence/claim graph."""
    conn = _connect(db_path)
    try:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        required = {'articles', 'analyses', 'events', 'event_articles', 'evidences', 'claims'}
        if not required.issubset(tables):
            return {'status': 'NOT_MEASURED', 'reason': 'required tables are absent',
                    'tables_present': sorted(tables)}
        counts = {table: _scalar(conn, f'SELECT COUNT(*) FROM {table}')
                  for table in ('articles', 'analyses', 'events', 'event_articles',
                                'evidences', 'claims', 'entities', 'entity_mentions',
                                'event_links', 'runs', 'deliveries')}
        locators = _scalar(conn, "SELECT COUNT(*) FROM claims WHERE locator_json NOT IN ('','{}')")
        cited = _scalar(conn, "SELECT COUNT(*) FROM claims WHERE quote<>''")
        states = {row[0]: row[1] for row in conn.execute(
            'SELECT verification_state, COUNT(*) FROM claims GROUP BY 1')}
        verified = states.get('verified', 0)
        unverifiable = states.get('unverifiable', 0)
        rejected = states.get('rejected', 0)
        events_with_evidence = _scalar(conn, """
            SELECT COUNT(DISTINCT ea.event_id) FROM event_articles ea
            JOIN evidences v USING(article_key)""")
        events_with_claims = _scalar(conn, """
            SELECT COUNT(DISTINCT ea.event_id) FROM event_articles ea
            JOIN claims c USING(article_key)""")
        multi_event = _scalar(conn, """
            SELECT COUNT(*) FROM (SELECT event_id FROM event_articles
                                  GROUP BY event_id HAVING COUNT(*)>1)""")
        independent = _scalar(conn, """
            SELECT COUNT(*) FROM (
              SELECT ea.event_id FROM event_articles ea
              JOIN evidences v USING(article_key)
              WHERE v.source_family<>''
                AND v.independence IN ('independent_primary','independent_secondary')
                AND (v.syndication_group IS NULL OR v.syndication_group='')
              GROUP BY ea.event_id
              HAVING COUNT(DISTINCT v.source_family)>=2)""")
        run_states = {row[0]: row[1] for row in conn.execute(
            'SELECT status, COUNT(*) FROM runs GROUP BY 1')}
        total_runs = sum(run_states.values())
        failed_runs = sum(n for status, n in run_states.items()
                          if status in ('failed', 'partial_failed', 'analysis_failed'))
        hold_runs = _scalar(conn, "SELECT COUNT(*) FROM runs WHERE publication_status='HOLD'")
        hold_deliveries = _scalar(conn, """
            SELECT COUNT(*) FROM deliveries d JOIN runs r USING(run_id)
            WHERE r.publication_status='HOLD'""")
        source_yield = [dict(row) for row in conn.execute("""
            SELECT a.source_id,
                   COUNT(DISTINCT a.article_key) AS articles,
                   COUNT(DISTINCT s.article_key) AS analysed,
                   COUNT(DISTINCT f.failure_id) AS failures
            FROM articles a LEFT JOIN analyses s USING(article_key)
            LEFT JOIN analysis_failures f ON f.url=a.url
            GROUP BY a.source_id ORDER BY articles DESC""")]
        # Model/prompt/rules version mix, read from the stored analysis payload. This is a
        # comparison of what actually ran, not a quality claim about any version.
        versions = {}
        for row in conn.execute('SELECT result_json FROM analyses'):
            try:
                meta = (json.loads(row[0] or '{}').get('meta') or {})
            except (TypeError, ValueError):
                meta = {}
            key = (str(meta.get('model') or 'unknown'),
                   str(meta.get('prompt_version') or 'unknown'),
                   str(meta.get('rules_version') or 'unknown'))
            entry = versions.setdefault('|'.join(key), {'model': key[0],
                                                         'prompt_version': key[1],
                                                         'rules_version': key[2],
                                                         'analyses': 0})
            entry['analyses'] += 1
        signal_detected = (_scalar(
            conn, "SELECT COUNT(*) FROM opportunities WHERE validation_state='signal_detected'")
            if 'opportunities' in tables else None)
        candidate_event_links = (_scalar(
            conn, """SELECT COUNT(*) FROM event_links
                    WHERE left_kind='event' AND right_kind='event' AND status='candidate'""")
            if 'event_links' in tables else None)
        located_unverified = _scalar(
            conn, """SELECT COUNT(*) FROM claims
                    WHERE verification_state<>'verified' AND locator_json NOT IN ('','{}')""")
        return {
            'status': 'PASS_MEASURED',
            'measured_at': datetime.now(timezone.utc).isoformat(),
            'tables': counts,
            'claims': {'total': counts['claims'], 'states': states,
                       'locator_rate_pct': _pct(locators, counts['claims']),
                       'quote_rate_pct': _pct(cited, counts['claims']),
                       'verified_rate_pct': _pct(verified, counts['claims']),
                       'unverifiable_rate_pct': _pct(unverifiable, counts['claims']),
                       'rejected_rate_pct': _pct(rejected, counts['claims'])},
            'events': {'total': counts['events'],
                       'with_evidence': events_with_evidence,
                       'with_claims': events_with_claims,
                       'multi_article': multi_event,
                       'evidence_coverage_pct': _pct(events_with_evidence, counts['events']),
                       'claim_coverage_pct': _pct(events_with_claims, counts['events']),
                       'independent_source_events': independent,
                       'independent_source_rate_pct': _pct(independent, counts['events']),
                       'clustering': {'status': 'NOT_MEASURED',
                                      'reason': 'no hand-labelled event-pair benchmark'}},
            'runs': {'total': total_runs, 'states': run_states,
                     'failure_rate_pct': _pct(failed_runs, total_runs),
                     'hold_runs': hold_runs,
                     'gate_escape_count': hold_deliveries,
                     'gate_escape_rate_pct': _pct(hold_deliveries, hold_runs)},
            'source_yield': source_yield,
            'versions': versions,
            # Discovery-layer counts. They make "how much is kept but not promoted"
            # measurable, so the weak-signal block can be checked against the database.
            'display': {'signal_detected_opportunities': signal_detected,
                        'candidate_event_links': candidate_event_links,
                        'located_unverified_claims': located_unverified},
        }
    finally:
        conn.close()


def backtest(db_path=DEFAULT_DB, days=30):
    """Run/coverage/delivery history for a fixed window ending now."""
    conn = _connect(db_path)
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = [dict(row) for row in conn.execute(
            '''SELECT run_id, started_at, finished_at, status, article_count,
                      analyzed_count, error_count, publication_status, coverage,
                      failed_causes, not_attempted
               FROM runs WHERE started_at>=? ORDER BY started_at''', (since,))]
        delivered = {row[0]: row[1] for row in conn.execute(
            '''SELECT r.run_id, COUNT(*) FROM deliveries d JOIN runs r USING(run_id)
               WHERE r.started_at>=? AND d.status='sent' GROUP BY r.run_id''', (since,))}
        for row in rows:
            row['sent_deliveries'] = delivered.get(row['run_id'], 0)
        ok = sum(1 for row in rows if row['status'] in ('success', 'dry_run', 'no_new_content'))
        coverages = [row['coverage'] for row in rows if row['coverage'] is not None]
        return {'days': days, 'runs': len(rows), 'successful_runs': ok,
                'run_success_rate_pct': _pct(ok, len(rows)),
                'mean_coverage_pct': round(100.0 * sum(coverages) / len(coverages), 2)
                if coverages else None,
                'deliveries': sum(row['sent_deliveries'] for row in rows),
                'details': rows}
    finally:
        conn.close()


def benchmark():
    """Read the frozen N1 benchmark result; it is a static reference, not a live score."""
    if not BENCHMARK_SUMMARY.exists():
        return _not_measured('benchmark summary is absent')
    try:
        data = json.loads(BENCHMARK_SUMMARY.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        return _not_measured(f'benchmark summary unreadable: {exc}')
    return {'status': 'PASS_STATIC', 'source': str(BENCHMARK_SUMMARY),
            'summary': data, 'note': 'frozen N1 benchmark; not re-run in this measurement'}


def _store(metrics_value, backtest_value, benchmark_value, db_path, quality_db):
    quality_db = Path(quality_db)
    quality_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(quality_db)
    try:
        conn.executescript(QUALITY_SCHEMA)
        stamp = datetime.now(timezone.utc).isoformat()
        run_id = 'q-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        conn.execute(
            'INSERT INTO quality_runs(run_id,measured_at,database,rules_version,metrics_json,'
            'backtest_json,benchmark_json) VALUES(?,?,?,?,?,?,?)',
            (run_id, stamp, str(db_path), RULES_VERSION,
             json.dumps(metrics_value, ensure_ascii=False, sort_keys=True, default=str),
             json.dumps(backtest_value, ensure_ascii=False, sort_keys=True, default=str),
             json.dumps(benchmark_value, ensure_ascii=False, sort_keys=True, default=str)))
        conn.commit()
        return run_id
    finally:
        conn.close()


def record(db_path=DEFAULT_DB, out_dir=DEFAULT_REPORT_DIR, quality_db=DEFAULT_QUALITY_DB,
           days=30):
    """Measure, persist and write a human-readable snapshot. Returns the measurement."""
    m = metrics(db_path)
    b = backtest(db_path, days=days)
    b90 = backtest(db_path, days=90)
    n = benchmark()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = {'rules_version': RULES_VERSION, 'database': str(db_path),
               'metrics': m, 'backtest': b, 'backtest_90': b90, 'benchmark': n}
    (out / 'latest.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    if m.get('status') == 'PASS_MEASURED':
        lines = ['# Opportunity Radar quality snapshot', '',
                 f"- measured_at: {m['measured_at']}",
                 f"- claims: {m['claims']['total']} · locator {m['claims']['locator_rate_pct']}%"
                 f" · verified {m['claims']['verified_rate_pct']}%",
                 f"- events: {m['events']['total']} · evidence coverage"
                 f" {m['events']['evidence_coverage_pct']}% · claim coverage"
                 f" {m['events']['claim_coverage_pct']}%",
                 f"- independent source events: {m['events']['independent_source_events']}",
                 f"- runs: {m['runs']['total']} · failure rate"
                 f" {m['runs']['failure_rate_pct']}% · gate escapes"
                 f" {m['runs']['gate_escape_count']}",
                 f"- backtest: {b['days']}d · {b['runs']} runs ·"
                 f" success {b['run_success_rate_pct']}%",
                 f"- backtest: 90d · {b90['runs']} runs ·"
                 f" success {b90['run_success_rate_pct']}%",
                 f"- benchmark: {n.get('status')}",
                 f"- display: signal_detected {m['display']['signal_detected_opportunities']}"
                 f" · candidate event links {m['display']['candidate_event_links']}"
                 f" · located-but-unverified claims {m['display']['located_unverified_claims']}"]
    else:
        lines = ['# Opportunity Radar quality snapshot', '',
                 f"- status: {m.get('status')}", f"- reason: {m.get('reason')}"]
    (out / 'latest.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    run_id = _store(m, {'30d': b, '90d': b90}, n, db_path, quality_db)
    return {'run_id': run_id, 'metrics': m, 'backtest': b, 'backtest_90': b90, 'benchmark': n,
            'report_dir': str(out)}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Measure and record R6 quality metrics')
    parser.add_argument('--db', default=str(DEFAULT_DB))
    parser.add_argument('--out', default=str(DEFAULT_REPORT_DIR))
    parser.add_argument('--quality-db', default=str(DEFAULT_QUALITY_DB))
    parser.add_argument('--days', type=int, default=30)
    args = parser.parse_args()
    print(json.dumps(record(args.db, args.out, args.quality_db, args.days),
                     ensure_ascii=False, indent=2, default=str))
