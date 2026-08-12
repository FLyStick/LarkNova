from __future__ import annotations

import json
import tempfile
import unittest

from feishu_agent.index.chunker import build_chunks, message_indexable

from support_index import add_chat, make_db, message


class ChunkingTests(unittest.TestCase):
    def test_time_window_splits_messages_into_deterministic_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            add_chat(db)
            db.upsert_message(
                message("m1", content="第一条", create_time="2026-08-11 10:00", sender_name="张三")
            )
            db.upsert_message(
                message("m2", content="第二条", create_time="2026-08-11 10:01", sender_name="李四")
            )
            db.upsert_message(
                message("m3", content="第三条", create_time="2026-08-11 12:00", sender_name="王五")
            )

            rows = db.query_messages(chat_id="oc_a")
            chunks, skipped = build_chunks(rows, gap_seconds=3600)
            self.assertEqual(len(chunks), 2)
            self.assertEqual(json.loads(chunks[0]["message_ids_json"]), ["m1", "m2"])
            self.assertEqual(json.loads(chunks[1]["message_ids_json"]), ["m3"])
            self.assertIn("第一条", chunks[0]["content"])
            self.assertIn("张三", chunks[0]["content"])
            self.assertEqual(skipped, {})

            again, _ = build_chunks(rows, gap_seconds=3600)
            self.assertEqual(
                [chunk["content_hash"] for chunk in chunks],
                [chunk["content_hash"] for chunk in again],
            )

    def test_thread_id_groups_messages_into_a_topic_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            add_chat(db)
            db.upsert_message(message("m1", content="开场", create_time="2026-08-11 10:00"))
            db.upsert_message(
                message(
                    "m2",
                    content="话题一",
                    create_time="2026-08-11 10:01",
                    thread_id="thread_1",
                    sender_name="李四",
                )
            )
            db.upsert_message(
                message(
                    "m3",
                    content="话题二",
                    create_time="2026-08-11 10:02",
                    thread_id="thread_1",
                    sender_name="王五",
                )
            )

            rows = db.query_messages(chat_id="oc_a")
            chunks, _ = build_chunks(rows, gap_seconds=3600)
            self.assertEqual(len(chunks), 2)
            self.assertTrue(chunks[0]["topic_key"].startswith("window:"))
            self.assertEqual(chunks[1]["topic_key"], "thread_1")
            self.assertEqual(json.loads(chunks[1]["message_ids_json"]), ["m2", "m3"])

    def test_message_indexable_skips_low_value_rows(self):
        self.assertTrue(
            message_indexable({"msg_type": "text", "content_normalized": "ok"})
        )
        self.assertFalse(
            message_indexable({"msg_type": "system", "content_normalized": "ok"})
        )
        self.assertFalse(
            message_indexable(
                {"msg_type": "text", "content_normalized": "ok", "deleted": 1}
            )
        )
        self.assertFalse(
            message_indexable({"msg_type": "text", "content_normalized": ""})
        )
        self.assertFalse(
            message_indexable(
                {
                    "msg_type": "text",
                    "content_normalized": "ok",
                    "normalize_error": "boom",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
