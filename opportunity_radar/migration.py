"""Explicit, guarded database migration for the RSS production store.

Ordinary commands open stores with migrate=False and receive a SchemaVersionError.
Only this module's apply path opens a writable store with migrate=True.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from . import unified

REQUIRED_COLUMNS = {
    'articles': {'source_id'},
    'entity_mentions': {'article_key', 'evidence_id', 'claim_id', 'locator_json', 'occurrence_count'},
}
REQUIRED_TABLES = {'entity_mentions', 'claim_corrections', 'entity_relations',
                   'opportunities', 'opportunity_links', 'opportunity_hypotheses',
                   'opportunity_revisions'}


def _connect(path):
    conn = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn, table):
    try:
        return {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
    except sqlite3.OperationalError:
        return set()


def plan(db_path):
    path = Path(db_path)
    if not path.exists():
        return {'db': str(path), 'exists': False, 'current_version': None,
                'target_version': unified.SCHEMA_VERSION, 'needs_migration': True,
                'missing_tables': sorted(REQUIRED_TABLES), 'missing_columns': {},
                'steps': ['database does not exist; create it with db-migrate --apply after a backup?']}
    conn = _connect(path)
    try:
        current = conn.execute('PRAGMA user_version').fetchone()[0]
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        missing_tables = sorted(REQUIRED_TABLES - tables)
        missing_columns = {}
        for table, columns in REQUIRED_COLUMNS.items():
            if table not in tables:
                continue
            absent = sorted(columns - _columns(conn, table))
            if absent:
                missing_columns[table] = absent
        steps = []
        if current < unified.SCHEMA_VERSION:
            steps.append(f'PRAGMA user_version: {current} -> {unified.SCHEMA_VERSION}')
        for table in missing_tables:
            steps.append(f'CREATE TABLE IF NOT EXISTS {table}')
        for table, columns in sorted(missing_columns.items()):
            for column in columns:
                steps.append(f'ALTER TABLE {table} ADD COLUMN {column}')
        return {'db': str(path), 'exists': True, 'current_version': current,
                'target_version': unified.SCHEMA_VERSION,
                'needs_migration': bool(steps), 'missing_tables': missing_tables,
                'missing_columns': missing_columns, 'steps': steps}
    finally:
        conn.close()


def _check_backup(backup):
    path = Path(backup)
    if not path.exists():
        raise ValueError(f'backup does not exist: {path}')
    conn = _connect(path)
    try:
        result = conn.execute('PRAGMA integrity_check').fetchone()[0]
    finally:
        conn.close()
    if result != 'ok':
        raise ValueError(f'backup integrity_check failed: {result}')
    return path


def migrate(db_path, apply=False, backup=None):
    before = plan(db_path)
    if not apply:
        return {'applied': False, **before}
    if not before['exists']:
        raise ValueError(f'database does not exist: {db_path}')
    if not backup:
        raise ValueError('--backup is required with --apply')
    backup_path = _check_backup(backup)
    if Path(db_path).resolve() == backup_path.resolve():
        raise ValueError('--backup must be a different file from --db')
    if before['current_version'] > unified.SCHEMA_VERSION:
        raise ValueError(f"database schema {before['current_version']} is newer than code {unified.SCHEMA_VERSION}")
    if not before['needs_migration']:
        return {'applied': False, 'already_current': True, 'backup': str(backup_path),
                'before': before, 'after': before}
    # Explicit apply: this is the only RSS path that opens a writable store with migrate=True.
    from .store import Store
    Store(str(db_path))
    unified.UnifiedStore(str(db_path))
    after = plan(db_path)
    if after['needs_migration']:
        raise RuntimeError(f"migration did not complete: {after['steps']}")
    return {'applied': True, 'backup': str(backup_path), 'before': before, 'after': after}
