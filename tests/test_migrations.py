from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from feishu_agent.database import db as db_module
from feishu_agent.database.db import Database


class MigrationTests(unittest.TestCase):
    def test_init_applies_migration_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent.db"
            db = Database(path)
            db.init()
            conn = sqlite3.connect(path)
            try:
                versions = [
                    row[0]
                    for row in conn.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    )
                ]
                self.assertEqual(versions, [2, 3, 4])
            finally:
                conn.close()
            db.init()
            conn = sqlite3.connect(path)
            try:
                versions = conn.execute(
                    "SELECT COUNT(*) FROM schema_migrations"
                ).fetchone()[0]
                self.assertEqual(versions, 3)
            finally:
                conn.close()

    def test_legacy_rows_are_backfilled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.db"
            conn = sqlite3.connect(path)
            try:
                conn.executescript(db_module.SCHEMA)
                conn.execute(
                    """
                    INSERT INTO messages (
                        message_id, chat_id, msg_type, content, raw_json, create_time
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "legacy1",
                        "oc_a",
                        "text",
                        "legacy body",
                        '{"message_id":"legacy1","chat_id":"oc_a","msg_type":"text","content":"legacy body"}',
                        "2026-08-11T10:00:00+08:00",
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            db = Database(path)
            db.init()
            rows = db.query_messages(chat_id="oc_a")
            self.assertEqual(rows[0]["content_normalized"], "legacy body")
            self.assertIsNotNone(rows[0]["content_hash"])
            versions = db.list_message_versions(message_id="legacy1")
            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0]["change_kind"], "initial")

            db.init()
            versions = db.list_message_versions(message_id="legacy1")
            self.assertEqual(len(versions), 1)


if __name__ == "__main__":
    unittest.main()
