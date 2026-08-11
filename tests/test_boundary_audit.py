from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from feishu_agent.boundary import audit_local_db, prune_local_db
from feishu_agent.database.db import Database


def message(message_id: str, chat_id: str) -> dict:
    return {
        "message_id": message_id,
        "chat_id": chat_id,
        "msg_type": "text",
        "content": {"text": f"body-{message_id}"},
        "create_time": "2026-08-11T10:00:00+08:00",
    }


class BoundaryAuditTests(unittest.TestCase):
    def test_audit_and_prune_local_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "agent.db")
            db.init()
            db.upsert_chat({"chat_id": "oc_a", "name": "A", "external": 0})
            db.upsert_chat({"chat_id": "oc_ext", "name": "External", "external": 1})
            db.upsert_chat({"chat_id": "oc_other", "name": "Other", "external": 0})
            db.upsert_message(message("m1", "oc_a"))
            db.upsert_message(message("m2", "oc_ext"))

            audit = audit_local_db(db, allowed_chat_ids={"oc_a", "oc_ext"}, allow_external=False)
            self.assertEqual(audit["chats_checked"], 3)
            self.assertEqual(audit["messages_to_remove"], 1)
            reasons = {item["reason"] for item in audit["chats_to_remove"]}
            self.assertEqual(reasons, {"external_chat", "not_in_whitelist"})

            removed = prune_local_db(db, [item["chat_id"] for item in audit["chats_to_remove"]])
            self.assertEqual(len(removed), 2)
            self.assertEqual(db.stats()["messages"], 1)
