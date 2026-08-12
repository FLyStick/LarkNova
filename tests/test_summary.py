from __future__ import annotations

import os
import tempfile
import unittest

from feishu_agent.config import Settings
from feishu_agent.index.repository import IndexRepository
from feishu_agent.summary.factory import make_summarizer
from feishu_agent.summary.protocol import SummaryConfigError
from feishu_agent.summary.repository import SummaryRepository
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


class SummaryRepositoryTests(unittest.TestCase):
    def test_rule_rebuild_is_traceable_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            add_chat(db, "oc_a", "Project")
            db.upsert_message(
                message(
                    "m1",
                    chat_id="oc_a",
                    content="proposal approved and the budget is confirmed",
                    create_time="2026-08-11 10:00:00",
                    sender_name="Wang",
                    position=1,
                )
            )
            db.upsert_message(
                message(
                    "m2",
                    chat_id="oc_a",
                    content="next step submit the procurement list tomorrow",
                    create_time="2026-08-11 10:01:00",
                    sender_name="Li",
                    position=2,
                )
            )

            IndexRepository(db).rebuild(chat_ids=["oc_a"])
            repo = SummaryRepository(db, Settings())
            first = repo.rebuild(
                chat_ids=["oc_a"],
                allowed_chat_ids={"oc_a"},
                mode="rule",
            )
            self.assertEqual(first["chats_checked"], 1)
            self.assertEqual(first["summaries_upserted"], 1)
            self.assertEqual(first["chats_failed"], 0)
            self.assertEqual(first["errors"], [])

            second = repo.rebuild(
                chat_ids=["oc_a"],
                allowed_chat_ids={"oc_a"},
                mode="rule",
            )
            self.assertEqual(second["summaries_upserted"], 1)

            items = repo.list_summaries(chat_ids=["oc_a"])
            self.assertEqual(len(items), 1)
            summary = items[0]
            self.assertEqual(summary["source_message_ids"], ["m1", "m2"])
            self.assertEqual(summary["messages_covered"], 2)
            self.assertEqual(
                list(summary["structure"].keys()),
                [
                    "conclusion",
                    "evidence",
                    "todo",
                    "key_people",
                    "key_dates",
                    "entities",
                ],
            )
            self.assertGreater(summary["input_tokens"], 0)

            consistency = repo.consistency(
                chat_ids=["oc_a"],
                allowed_chat_ids={"oc_a"},
            )
            self.assertTrue(consistency["consistent"])
            self.assertTrue(consistency["per_chat"][0]["has_summary"])

            status = repo.status()
            self.assertTrue(status["built"])
            self.assertTrue(status["fresh"])
            self.assertEqual(status["counts"]["summaries"], 1)

            metrics = db.metrics()
            self.assertEqual(metrics["summary"]["runs_total"], 2)
            self.assertGreater(metrics["summary"]["token_estimate"], 0)
            self.assertEqual(metrics["stats"]["summaries"], 1)

    def test_incremental_refreshes_after_new_messages_and_noops(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            add_chat(db, "oc_a", "Project")
            db.upsert_message(
                message(
                    "m1",
                    chat_id="oc_a",
                    content="baseline message body",
                    create_time="2026-08-11 10:00:00",
                    sender_name="Wang",
                    position=1,
                )
            )
            IndexRepository(db).rebuild(chat_ids=["oc_a"])
            repo = SummaryRepository(db, Settings())
            repo.rebuild(chat_ids=["oc_a"], allowed_chat_ids={"oc_a"})

            noop = repo.incremental(
                chat_ids=["oc_a"],
                allowed_chat_ids={"oc_a"},
            )
            self.assertFalse(noop["built"])
            self.assertEqual(noop["reason"], "no_changes")

            db.upsert_message(
                message(
                    "m2",
                    chat_id="oc_a",
                    content="new message with follow-up action",
                    create_time="2026-08-11 10:02:00",
                    sender_name="Li",
                    position=2,
                )
            )
            IndexRepository(db).incremental(
                chat_ids=["oc_a"],
                allowed_chat_ids={"oc_a"},
            )
            refreshed = repo.incremental(
                chat_ids=["oc_a"],
                allowed_chat_ids={"oc_a"},
            )
            self.assertTrue(refreshed["built"])
            self.assertEqual(refreshed["reason"], "summarized")
            self.assertEqual(refreshed["summaries_upserted"], 1)

            latest = repo.get("oc_a")
            self.assertIn("m2", latest["source_message_ids"])
            self.assertEqual(len(repo.list_summaries(chat_ids=["oc_a"])), 1)

    def test_incremental_without_index_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            add_chat(db)
            db.upsert_message(message("m1", content="body"))
            repo = SummaryRepository(db, Settings())
            result = repo.incremental(
                chat_ids=["oc_a"],
                allowed_chat_ids={"oc_a"},
            )
            self.assertFalse(result["built"])
            self.assertEqual(result["reason"], "no_index")

    def test_llm_without_url_raises_config_error(self):
        old = os.environ.pop("FEISHU_AGENT_LLM_API_URL", None)
        try:
            summarizer = make_summarizer("llm", Settings())
            with self.assertRaises(SummaryConfigError):
                summarizer.summarize_chat(
                    "oc_a",
                    "Project",
                    [],
                    "2026-08-11T10:00:00+08:00",
                )
        finally:
            if old is not None:
                os.environ["FEISHU_AGENT_LLM_API_URL"] = old

    def test_sync_all_hooks_incremental_summary(self):
        chats = [{"chat_id": "oc_a", "name": "Project", "external": 0}]
        client = FakeClient(
            chats,
            {
                "oc_a": [
                    message(
                        "m1",
                        chat_id="oc_a",
                        content="baseline message body",
                        create_time="2026-08-11 10:00:00",
                        sender_name="Wang",
                        position=1,
                    )
                ]
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            runner = SyncRunner(
                client,
                db,
                allowed_chat_ids={"oc_a"},
                summary_factory=lambda: SummaryRepository(db, Settings()),
            )
            first = runner.sync_all()
            self.assertEqual(first["summary"]["reason"], "no_index")

            IndexRepository(db).rebuild(allowed_chat_ids={"oc_a"})
            client.messages["oc_a"].append(
                message(
                    "m2",
                    chat_id="oc_a",
                    content="new follow-up action message",
                    create_time="2026-08-11 10:02:00",
                    sender_name="Li",
                    position=2,
                )
            )
            second = runner.sync_all()
            self.assertEqual(second["messages_new"], 1)
            self.assertEqual(second["chats_failed"], 0)
            self.assertEqual(second["errors"], [])
            self.assertTrue(second["summary"]["built"])
            self.assertEqual(second["summary"]["summaries_upserted"], 1)
            self.assertEqual(db.stats()["summaries"], 1)


if __name__ == "__main__":
    unittest.main()
