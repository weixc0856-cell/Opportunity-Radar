"""Append-only storage for N0/N1 node runs.

This is deliberately not the production database. The claim pipeline is offline, and its
records must survive a rerun and a version change without ever overwriting the earlier
result: the primary key includes the node version, the input hash and the parameters, and
rows are inserted with INSERT OR IGNORE. A changed input, rule set or version therefore
produces a new row and the old row stays readable.

Nothing here calls a model or touches the RSS business tables.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS node_runs(
    article_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    node_name TEXT NOT NULL,
    node_version TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    output_hash TEXT NOT NULL,
    execution_status TEXT NOT NULL,
    executed_at TEXT NOT NULL,
    params_json TEXT NOT NULL,
    tools_json TEXT NOT NULL,
    output_json TEXT NOT NULL,
    PRIMARY KEY (article_id, node_name, node_version, input_hash, params_json)
)
"""


def _canonical(value):
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class PipelineStore:
    """One SQLite file holding append-only node runs."""

    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute(SCHEMA)
            conn.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

    @contextmanager
    def connect(self):
        """A connection that commits on success and always closes (Windows keeps the file
        locked otherwise, which breaks a temp-directory cleanup or a later move)."""
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def find(self, article_id, node_name, node_version, input_hash, params=None):
        """The stored output for this exact run, or None. Only completed runs are reused."""
        with self.connect() as conn:
            row = conn.execute(
                'SELECT output_json FROM node_runs WHERE article_id=? AND node_name=? '
                'AND node_version=? AND input_hash=? AND params_json=? '
                "AND execution_status='ok'",
                (article_id, node_name, node_version, input_hash, _canonical(params))
            ).fetchone()
        return json.loads(row['output_json']) if row else None

    def record(self, *, article_id, document_id, content_hash, node_name, node_version,
               input_hash, output, params=None, tools=None, status='ok', executed_at=None):
        """Insert one run. Returns (inserted, output_hash); an identical run is left alone."""
        output_json = json.dumps(output, ensure_ascii=False, sort_keys=True)
        # A failed run must not occupy the key of a later successful run: the primary key is
        # the reuse key, so a failure gets a status marker in its parameters and a success
        # keeps the plain parameters. Otherwise one transient failure would make `find`
        # return None forever while the successful record was silently ignored.
        key_params = dict(params or {})
        if status != 'ok':
            key_params['_status'] = status
        params_json = _canonical(key_params)
        tools_json = _canonical(tools)
        output_hash = hashlib.sha256(output_json.encode('utf-8')).hexdigest()
        executed_at = executed_at or datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            cursor = conn.execute(
                'INSERT OR IGNORE INTO node_runs(article_id, document_id, content_hash, '
                'node_name, node_version, input_hash, output_hash, execution_status, '
                'executed_at, params_json, tools_json, output_json) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (article_id, document_id, content_hash, node_name, node_version, input_hash,
                 output_hash, status, executed_at, params_json, tools_json, output_json))
            inserted = cursor.rowcount > 0
        return inserted, output_hash

    def find_latest(self, article_id, node_name, node_version, input_hash):
        """The newest usable result for this exact input, across retries/parameter variants.

        Failed attempts stay in history but are skipped; a later retry therefore becomes
        discoverable without deleting the failure. This is the resume path for N2/N3/N4/N5.
        """
        unusable = {'failed', 'invalid_output', 'model_unavailable', 'timeout', 'schema_error'}
        with self.connect() as conn:
            rows = conn.execute(
                'SELECT output_json FROM node_runs WHERE article_id=? AND node_name=? '
                'AND node_version=? AND input_hash=? AND execution_status=? '
                'ORDER BY executed_at DESC',
                (article_id, node_name, node_version, input_hash, 'ok')
            ).fetchall()
        for row in rows:
            try:
                output = json.loads(row['output_json'])
            except (TypeError, ValueError):
                continue
            if output.get('status') not in unusable:
                return output
        return None

    def find_latest_document(self, article_id, node_name, node_version, document_id):
        """Newest usable result for the same N0 document, even when the input hash differs.

        document_id is sha256(n0 version + content hash), so a match proves the text is the
        same. This is the fallback for a metrics-only code change: the semantic output is
        still valid and the successful run must not be thrown away or overwritten.
        """
        if not document_id:
            return None
        unusable = {'failed', 'invalid_output', 'model_unavailable', 'timeout', 'schema_error'}
        with self.connect() as conn:
            rows = conn.execute(
                'SELECT output_json FROM node_runs WHERE article_id=? AND node_name=? '
                'AND node_version=? AND execution_status=? ORDER BY executed_at DESC',
                (article_id, node_name, node_version, 'ok')
            ).fetchall()
        for row in rows:
            try:
                output = json.loads(row['output_json'])
            except (TypeError, ValueError):
                continue
            if output.get('document_id') != document_id:
                continue
            if output.get('status') not in unusable:
                return output
        return None

    def runs(self, article_id=None):
        """Every recorded run, newest first, without the possibly large output payload."""
        query = ('SELECT article_id, document_id, content_hash, node_name, node_version, '
                 'input_hash, output_hash, execution_status, executed_at, params_json, '
                 'tools_json FROM node_runs')
        params = ()
        if article_id is not None:
            query += ' WHERE article_id=?'
            params = (article_id,)
        query += ' ORDER BY executed_at DESC'
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(query, params)]
