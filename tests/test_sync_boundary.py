from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from feishu_agent.database.db import Database
from feishu_agent.sync.runner import SyncRunner, boundary_reason


class FakeClient:
    def __init__(self, chats, messages=None):
        self.chats = chats
        self.messages = messages or {}
        self.list_messages_calls = []

    def list_chats(self, identity=None):
        return [dict(chat) for chat in self.chats]

    def list_messages(self, chat_id, identity=None, order="asc", page_size=50, start=None, end=None, page_all=True):
        self.list_messages_calls.append(
            {"chat_id": chat_id, "identity": identity, "order": order, "page_all": page_all}
        )
        return [dict(message) for message in self.messages.get(chat_id, [])]


def message(message_id, chat_id):
    return {
        "message_id": message_id,
        "chat_id": chat_id,
        "msg_type": "text",
        "content": f"body-{message_id}",
        "create_time": "2026-08-11T10:00:00+08:00",
    }


class BoundaryTests(unittest.TestCase):
    def test_boundary_reason_priority(self):
        self.assertIsNone(boundary_reason("oc_a", False, {"oc_a"}, False))
        self.assertEqual(boundary_reason("oc_b", False, {"oc_a"}, False), "not_in_whitelist")
        self.assertEqual(boundary_reason("oc_a", True, {"oc_a"}, False), "external_chat")
        self.assertIsNone(boundary_reason("oc_a", True, {"oc_a"}, True))

    def test_sync_skips_external_and_non_whitelist(self):
        chats = [
            {"chat_id": "oc_a", "name": "A", "external": 0},
            {"chat_id": "oc_b", "name": "External", "external": 1},
            {"chat_id": "oc_c", "name": "C", "external": 0},
        ]
        client = FakeClient(
            chats,
            {
                "oc_a": [message("m1", "oc_a")],
                "oc_b": [message("m2", "oc_b")],
                "oc_c": [message("m3", "oc_c")],
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "agent.db")
            db.init()
            runner = SyncRunner(client, db, allowed_chat_ids={"oc_a", "oc_b"})
            result = runner.sync_all()
            self.assertEqual(result["chats_allowed"], 1)
            self.assertEqual(
                {item["reason"] for item in result["chats_skipped"]},
                {"external_chat", "not_in_whitelist"},
            )
            self.assertEqual((db.stats()["chats"], db.stats()["messages"]), (1, 1))

    def test_explicit_chat_id_must_still_pass_whitelist(self):
        chats = [
            {"chat_id": "oc_a", "name": "A", "external": 0},
            {"chat_id": "oc_b", "name": "B", "external": 0},
        ]
        client = FakeClient(
            chats,
            {
                "oc_a": [message("m1", "oc_a")],
                "oc_b": [message("m2", "oc_b")],
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "agent.db")
            db.init()
            runner = SyncRunner(client, db, allowed_chat_ids={"oc_a"})
            result = runner.sync_all(chat_ids=["oc_b"])
            self.assertEqual(result["messages_new"], 0)
            self.assertEqual([item["chat_id"] for item in result["chats_skipped"]], ["oc_b"])
            self.assertEqual(db.stats()["messages"], 0)

    def test_allow_external_syncs_external(self):
        chats = [
            {"chat_id": "oc_a", "name": "A", "external": 0},
            {"chat_id": "oc_b", "name": "External", "external": 1},
        ]
        client = FakeClient(
            chats,
            {
                "oc_a": [message("m1", "oc_a")],
                "oc_b": [message("m2", "oc_b")],
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "agent.db")
            db.init()
            runner = SyncRunner(client, db, allowed_chat_ids={"oc_a", "oc_b"}, allow_external=True)
            result = runner.sync_all()
            self.assertEqual(result["chats_allowed"], 2)
            self.assertEqual(result["chats_skipped"], [])
            self.assertEqual(db.stats()["messages"], 2)

    def test_sync_is_idempotent(self):
        chats = [{"chat_id": "oc_a", "name": "A", "external": 0}]
        client = FakeClient(chats, {"oc_a": [message("m1", "oc_a")]})
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "agent.db")
            db.init()
            runner = SyncRunner(client, db)
            first = runner.sync_chat("oc_a")
            second = runner.sync_chat("oc_a")
            self.assertEqual(
                (first["new"], second["new"], second["unchanged"]),
                (1, 0, 1),
            )
            self.assertEqual(db.stats()["messages"], 1)


if __name__ == "__main__":
    unittest.main()
