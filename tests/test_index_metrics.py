from __future__ import annotations

import sqlite3
import tempfile
import unittest

from feishu_agent.index.repository import IndexRepository
from feishu_agent.sync.runner import SyncRunner

from support_index import add_chat, make_db, message


class FakeClient:
    def __init__(self, chats, messages=None):
        self.chats = chats
        self.messages = messages or {}

    def list_chats(self, identity=None):
        return [dict(chat) for chat in self.chats]

    def list_messages(
        self,
        chat_id,
        identity=None,
        order="asc",
        page_size=50,
        start=None,
        end=None,
        page_all=True,
    ):
        return [dict(item) for item in self.messages.get(chat_id, [])]


class IndexMetricsTests(unittest.TestCase):
    def test_incremental_rebuilds_only_changed_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            add_chat(db, "oc_a", "A组")
            add_chat(db, "oc_b", "B组")
            db.upsert_message(
                message(
                    "m1",
                    chat_id="oc_a",
                    content="甲类预算",
                    create_time="2026-08-11 10:00",
                    sender_name="王芳",
                )
            )
            db.upsert_message(
                message(
                    "m2",
                    chat_id="oc_b",
                    content="乙类流程",
                    create_time="2026-08-11 10:00",
                    sender_name="李雷",
                )
            )

            repo = IndexRepository(db)
            built = repo.rebuild(allowed_chat_ids={"oc_a", "oc_b"})
            self.assertEqual(built["chats_indexed"], 2)

            db.upsert_message(
                message(
                    "m3",
                    chat_id="oc_a",
                    content="新增预算明细",
                    create_time="2026-08-11 10:01",
                    sender_name="王芳",
                )
            )
            inc = repo.incremental(allowed_chat_ids={"oc_a", "oc_b"})
            self.assertTrue(inc["built"])
            self.assertEqual(inc["chats_changed"], 1)
            self.assertEqual(inc["chats_indexed"], 1)
            self.assertEqual(inc["messages_indexed"], 2)

            res = repo.search("明细", chat_ids=["oc_a"])
            self.assertIn("m3", res["results"][0]["message_ids"])

            noop = repo.incremental(allowed_chat_ids={"oc_a", "oc_b"})
            self.assertFalse(noop["built"])
            self.assertEqual(noop["reason"], "no_changes")

            check = repo.consistency(allowed_chat_ids={"oc_a", "oc_b"})
            self.assertTrue(check["consistent"])

    def test_incremental_without_rebuild_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            add_chat(db)
            db.upsert_message(message("m1", content="hello"))
            repo = IndexRepository(db)
            result = repo.incremental(allowed_chat_ids={"oc_a"})
            self.assertFalse(result["built"])
            self.assertEqual(result["reason"], "no_rebuild_yet")

    def test_sync_all_hooks_incremental_index(self):
        chats = [{"chat_id": "oc_a", "name": "A组", "external": 0}]
        client = FakeClient(
            chats,
            {
                "oc_a": [
                    message(
                        "m1",
                        chat_id="oc_a",
                        content="基线消息",
                        create_time="2026-08-11 10:00",
                    )
                ]
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            runner = SyncRunner(client, db, allowed_chat_ids={"oc_a"})
            first = runner.sync_all()
            self.assertEqual(first["index"]["reason"], "no_rebuild_yet")
            self.assertEqual(first["chats_failed"], 0)
            self.assertEqual(first["errors"], [])

            repo = IndexRepository(db)
            self.assertEqual(repo.rebuild(allowed_chat_ids={"oc_a"})["chats_indexed"], 1)

            client.messages["oc_a"].append(
                message(
                    "m2",
                    chat_id="oc_a",
                    content="增量消息",
                    create_time="2026-08-11 10:01",
                )
            )
            second = runner.sync_all()
            self.assertTrue(second["index"]["built"])
            self.assertEqual(second["messages_new"], 1)
            self.assertEqual(second["chats_failed"], 0)
            self.assertEqual(second["errors"], [])
            self.assertEqual(len(db.recent_sync_runs()), 2)

    def test_sync_swallows_index_failure(self):
        chats = [{"chat_id": "oc_a", "name": "A组", "external": 0}]
        client = FakeClient(
            chats,
            {
                "oc_a": [
                    message(
                        "m1",
                        chat_id="oc_a",
                        content="基线消息",
                        create_time="2026-08-11 10:00",
                    )
                ]
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            runner = SyncRunner(client, db, allowed_chat_ids={"oc_a"})
            runner.sync_all()
            repo = IndexRepository(db)
            repo.rebuild(allowed_chat_ids={"oc_a"})

            conn = sqlite3.connect(db.db_path)
            try:
                conn.execute("DROP TABLE chunks")
                conn.commit()
            finally:
                conn.close()

            client.messages["oc_a"].append(
                message(
                    "m2",
                    chat_id="oc_a",
                    content="增量消息",
                    create_time="2026-08-11 10:01",
                )
            )
            result = runner.sync_all()
            self.assertIn("error", result["index"])
            self.assertEqual(result["chats_failed"], 0)
            self.assertEqual(result["errors"], [])


if __name__ == "__main__":
    unittest.main()
