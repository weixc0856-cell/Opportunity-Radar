import contextlib
import io
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from opportunity_radar import migration, unified, unified_main
from opportunity_radar.store import Store
from opportunity_radar.unified import SchemaVersionError


class MigrationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'db.sqlite3'
        Store(str(self.db))
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            conn.execute('DROP TABLE IF EXISTS claim_corrections')
            conn.execute('DROP TABLE IF EXISTS entity_relations')
            conn.execute('PRAGMA user_version = 5')
            conn.commit()

    def tearDown(self):
        self.tmp.cleanup()

    def version(self):
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            return conn.execute('PRAGMA user_version').fetchone()[0]

    def test_guarded_store_rejects_old_schema_without_migrating(self):
        with self.assertRaises(SchemaVersionError):
            Store(str(self.db), migrate=False)
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='claim_corrections'").fetchone()
        self.assertEqual(self.version(), 5)
        self.assertIsNone(table)

    def test_guarded_unified_store_rejects_old_schema_without_migrating(self):
        with self.assertRaises(SchemaVersionError):
            unified.UnifiedStore(str(self.db), migrate=False)
        self.assertEqual(self.version(), 5)

    def test_plan_is_read_only(self):
        result = migration.plan(str(self.db))
        self.assertTrue(result['needs_migration'])
        self.assertIn('claim_corrections', result['missing_tables'])
        self.assertEqual(self.version(), 5)

    def test_apply_requires_a_backup_and_does_not_write_without_one(self):
        with self.assertRaises(ValueError):
            migration.migrate(str(self.db), apply=True)
        self.assertEqual(self.version(), 5)

    def test_apply_with_backup_migrates_and_verifies(self):
        backup = Path(self.tmp.name) / 'backup.sqlite3'
        shutil.copy2(self.db, backup)
        result = migration.migrate(str(self.db), apply=True, backup=str(backup))
        self.assertTrue(result['applied'])
        self.assertEqual(result['after']['current_version'], unified.SCHEMA_VERSION)
        self.assertFalse(result['after']['needs_migration'])
        with contextlib.closing(sqlite3.connect(self.db)) as conn:
            self.assertIsNotNone(conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='entity_relations'").fetchone())

    def test_db_migrate_cli_dry_run_is_read_only(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = unified_main.main(['db-migrate', '--db', str(self.db)])
        self.assertEqual(code, 0)
        self.assertEqual(self.version(), 5)
        self.assertIn('needs_migration', output.getvalue())

    def test_db_migrate_cli_apply_requires_backup(self):
        with contextlib.redirect_stderr(io.StringIO()):
            code = unified_main.main(['db-migrate', '--db', str(self.db), '--apply'])
        self.assertEqual(code, 2)
        self.assertEqual(self.version(), 5)


if __name__ == '__main__':
    unittest.main()
