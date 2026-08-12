from __future__ import annotations

import tempfile
import unittest

from feishu_agent.index.repository import IndexRepository

from support_index import add_chat, make_db, message


class IndexSearchTests(unittest.TestCase):
    def test_rebuild_search_and_consistency_are_traceable(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            add_chat(db)
            db.upsert_message(
                message(
                    "m1",
                    content="人事部发布招聘计划，预算3万元，截止5月10日",
                    sender_name="王芳",
                    create_time="2026-08-11 10:00",
                )
            )
            db.upsert_message(
                message(
                    "m2",
                    content="openai agent rag lark 知识库检索",
                    sender_name="李雷",
                    create_time="2026-08-11 10:01",
                )
            )
            db.upsert_message(
                message(
                    "m3",
                    content="系统通知",
                    sender_name="飞书",
                    msg_type="system",
                    create_time="2026-08-11 10:02",
                )
            )

            repo = IndexRepository(db)
            built = repo.rebuild(chat_ids=["oc_a"])
            self.assertEqual(built["chats_failed"], 0)
            self.assertEqual(built["messages_indexed"], 2)
            self.assertGreaterEqual(built["chunks_created"], 1)

            res = repo.search("招聘", chat_ids=["oc_a"])
            self.assertEqual(res["total"], 1)
            first = res["results"][0]
            self.assertEqual(first["chat_id"], "oc_a")
            self.assertIn("m1", first["message_ids"])
            self.assertEqual(first["message_id_start"], "m1")
            self.assertEqual(first["messages"][0]["sender_name"], "王芳")
            self.assertEqual(first["create_time"], "2026-08-11 10:00")
            self.assertIn("招聘", first["content"])
            self.assertTrue(first["sources"])

            res = repo.search("openai", chat_ids=["oc_a"])
            self.assertGreaterEqual(res["total"], 1)
            self.assertIn("m2", res["results"][0]["message_ids"])

            status = repo.status()
            self.assertTrue(status["indexed"])
            self.assertTrue(status["fresh"])
            self.assertEqual(status["counts"]["chunks"], 1)
            self.assertEqual(status["counts"]["fts_rows"], 1)
            self.assertEqual(status["counts"]["vectors"], 1)

            check = repo.consistency(chat_ids=["oc_a"])
            self.assertTrue(check["consistent"])
            self.assertEqual(check["per_chat"][0]["expected_indexable"], 2)
            self.assertEqual(check["per_chat"][0]["indexed"], 2)


if __name__ == "__main__":
    unittest.main()
