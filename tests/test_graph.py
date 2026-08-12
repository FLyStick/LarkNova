from __future__ import annotations

import json
import tempfile
import unittest

from feishu_agent.index.graph import (
    entity_id,
    extract_message_entities,
    reply_to_message_id,
)
from feishu_agent.index.repository import IndexRepository

from support_index import add_chat, make_db, message


class GraphExtractionTests(unittest.TestCase):
    def test_rule_extraction_covers_entities_and_reply(self):
        msg = {
            "content_normalized": (
                "人事部 王芳 5月10日 预算3万元 https://www.sczxlq.com oc_abc123"
            ),
            "sender_name": "李雷",
            "mentions": [{"name": "王芳"}],
        }
        entities = extract_message_entities(msg, chat_name="项目组", chat_id="oc_a")
        types = {item["entity_type"] for item in entities}
        self.assertTrue(
            {"person", "group", "department", "date", "identifier", "url", "amount"}
            <= types
        )
        self.assertEqual(reply_to_message_id({"reply_to": "om_m1"}), "om_m1")
        self.assertEqual(
            reply_to_message_id(
                {"raw_json": json.dumps({"reply": {"message_id": "om_m2"}})}
            ),
            "om_m2",
        )
        self.assertEqual(len(entity_id("person", "王芳")), 64)

    def test_graph_tracks_cooccurrence_and_reply_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            add_chat(db, name="项目组")
            db.upsert_message(
                message(
                    "m1",
                    content="人事部招聘 5月10日 预算3万元",
                    sender_name="王芳",
                    create_time="2026-08-11 10:00",
                )
            )
            db.upsert_message(
                message(
                    "m2",
                    content="我确认预算，联系王芳",
                    sender_name="李雷",
                    create_time="2026-08-11 10:01",
                    reply_message_id="m1",
                )
            )
            db.upsert_message(
                message(
                    "m3",
                    content="财务部审批通过",
                    sender_name="王芳",
                    create_time="2026-08-11 10:02",
                )
            )

            repo = IndexRepository(db)
            built = repo.rebuild(chat_ids=["oc_a"])
            self.assertEqual(built["chats_failed"], 0)
            self.assertGreaterEqual(built["entities_created"], 4)

            result = repo.query_graph("王芳")
            self.assertTrue(result["found"])
            neighbor_values = {item["value"] for item in result["neighbors"]}
            self.assertIn("李雷", neighbor_values)
            self.assertIn("人事部", neighbor_values)
            self.assertIn("replied_to", {item["edge_type"] for item in result["neighbors"]})
            message_ids = {item["message_id"] for item in result["messages"]}
            self.assertIn("m1", message_ids)
            self.assertIn("m3", message_ids)

            stats = repo.entity_stats()
            self.assertGreaterEqual(stats["totals"]["entities"], 4)
            self.assertGreaterEqual(stats["totals"]["edges"], 3)


if __name__ == "__main__":
    unittest.main()
