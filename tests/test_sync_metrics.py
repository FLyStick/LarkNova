from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from feishu_agent.database.db import Database
from feishu_agent.sync.runner import SyncRunner


class FakeClient:
    def __init__(self, chats, messages=None, fail_chat_ids=None):
        self.chats = chats
        self.messages = messages or {}
        self.fail_chat_ids = set(fail_chat_ids or [])
        self.list_messages_calls = []

    def list_chats(self, identity=None):
        return [dict(chat) for chat in self.chats]

    def list_messages(self, chat_id, identity=None, order="asc", page_size=50, start=None, end=None, page_all=True):
        self.list_messages_calls.append(
            {
                "chat_id": chat_id,
                "identity": identity,
                "order": order,
                "page_all": page_all,
                "start": start,
            }
        )
        if chat_id in self.fail_chat_ids:
            raise RuntimeError(f"failed {chat_id}")
        return [dict(message) for message in self.messages.get(chat_id, [])]


def message(message_id, chat_id, content=None, deleted=False, updated=False):
    return {
        "message_id": message_id,
        "chat_id": chat_id,
        "msg_type": "text",
        "content": content or f"body-{message_id}",
        "create_time": "2026-08-11T10:00:00+08:00",
        "deleted": deleted,
        "updated": updated,
    }


class SyncMetricsTests(unittest.TestCase):
    def test_sync_all_records_runs_and_is_idempotent(self):
        chats = [{"chat_id": "oc_a", "name": "A", "external": 0}]
        client = FakeClient(chats, {"oc_a": [message("m1", "oc_a")]})
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "agent.db")
            db.init()
            runner = SyncRunner(client, db)
            first = runner.sync_all()
            second = runner.sync_all()
            self.assertEqual(first["messages_new"], 1)
            self.assertEqual(
                (second["messages_new"], second["messages_updated"]),
                (0, 0),
            )
            runs = db.recent_sync_runs(limit=10)
            self.assertEqual(len(runs), 2)
            self.assertEqual(runs[0]["errors"], [])
            metrics = db.metrics()
            self.assertEqual(metrics["sync_runs_total"], 2)
            self.assertEqual(metrics["stats"]["messages"], 1)
            self.assertEqual(metrics["totals"]["messages_new"], 1)

    def test_one_chat_failure_does_not_block_others(self):
        chats = [
            {"chat_id": "oc_a", "name": "A", "external": 0},
            {"chat_id": "oc_b", "name": "B", "external": 0},
        ]
        client = FakeClient(
            chats,
            {"oc_a": [message("m1", "oc_a")]},
            fail_chat_ids=["oc_b"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "agent.db")
            db.init()
            runner = SyncRunner(client, db)
            result = runner.sync_all()
            self.assertEqual(result["chats_allowed"], 2)
            self.assertEqual(result["chats_failed"], 1)
            self.assertEqual(result["messages_new"], 1)
            self.assertEqual(db.stats()["messages"], 1)
            state = db.get_sync_state("oc_b")
            self.assertEqual(state["status"], "error")
            self.assertIn("failed oc_b", state["error"])
            runs = db.recent_sync_runs(limit=1)
            self.assertEqual(len(runs[0]["errors"]), 1)
            self.assertEqual(runs[0]["errors"][0]["chat_id"], "oc_b")

    def test_updated_recalled_restored_counts_and_versions(self):
        chats = [{"chat_id": "oc_a", "name": "A", "external": 0}]
        messages = {
            "oc_a": [
                message("m1", "oc_a", content="v1"),
                message("m2", "oc_a", content="old"),
            ]
        }
        client = FakeClient(chats, messages)
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "agent.db")
            db.init()
            runner = SyncRunner(client, db)
            first = runner.sync_all()
            self.assertEqual(first["messages_new"], 2)

            messages["oc_a"] = [
                message("m1", "oc_a", content="v2", updated=True),
                message("m2", "oc_a", content="old", deleted=True),
                message("m3", "oc_a"),
            ]
            second = runner.sync_all()
            self.assertEqual(
                (
                    second["messages_updated"],
                    second["messages_deleted"],
                    second["messages_new"],
                ),
                (1, 1, 1),
            )

            messages["oc_a"] = [
                message("m2", "oc_a", content="old"),
            ]
            third = runner.sync_all()
            self.assertEqual(third["messages_restored"], 1)
            self.assertEqual(db.stats()["versions"], 6)

    def test_empty_incremental_run_preserves_cursor(self):
        chats = [{"chat_id": "oc_a", "name": "A", "external": 0}]
        client = FakeClient(chats, {"oc_a": [message("m1", "oc_a")]})
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "agent.db")
            db.init()
            runner = SyncRunner(client, db)
            runner.sync_chat("oc_a")
            first_state = db.get_sync_state("oc_a")
            client.messages["oc_a"] = []
            runner.sync_chat("oc_a")
            second_state = db.get_sync_state("oc_a")
            self.assertEqual(
                second_state["last_message_time"],
                first_state["last_message_time"],
            )
            self.assertEqual(second_state["status"], "ok")


if __name__ == "__main__":
    unittest.main()
