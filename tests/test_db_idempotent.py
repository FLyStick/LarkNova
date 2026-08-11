from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from feishu_agent.database.db import Database


class DbIdempotenceTests(unittest.TestCase):
    def test_upsert_same_message_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "agent.db")
            db.init()
            first = {
                "message_id": "m1",
                "chat_id": "oc_a",
                "msg_type": "text",
                "content": {"text": "v1"},
                "create_time": "2026-08-11T10:00:00+08:00",
            }
            second = {**first, "content": {"text": "v2"}, "updated": True}
            created = db.upsert_message(first)
            updated = db.upsert_message(second)
            unchanged = db.upsert_message(second)
            self.assertEqual(
                (
                    created["status"],
                    updated["status"],
                    updated["change_kind"],
                    unchanged["status"],
                ),
                ("created", "updated", "content_updated", "unchanged"),
            )
            self.assertEqual(
                (db.stats()["messages"], db.stats()["versions"]),
                (1, 2),
            )
            rows = db.query_messages(chat_id="oc_a")
            self.assertEqual(rows[0]["updated"], 1)
            self.assertIn("v2", rows[0]["content"])
            versions = db.list_message_versions(message_id="m1")
            self.assertEqual(
                [row["change_kind"] for row in versions],
                ["created", "content_updated"],
            )


if __name__ == "__main__":
    unittest.main()
