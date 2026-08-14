from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from feishu_agent.config import Settings
from feishu_agent.database.db import Database
from feishu_agent.index.repository import IndexRepository
from feishu_agent.summary.repository import SummaryRepository
from feishu_agent.synthetic import (
    GOLDEN_MESSAGE_IDS,
    TOTAL_MESSAGES,
    build_messages,
    message_id_for,
    seed_database,
    synthetic_status,
)


class SyntheticCorpusTests(unittest.TestCase):
    def test_build_messages_is_deterministic_and_capped(self):
        first = build_messages(limit=10)
        second = build_messages(limit=10)
        self.assertEqual(len(first), 10)
        self.assertEqual(
            [message["message_id"] for message in first],
            [message["message_id"] for message in second],
        )
        full = build_messages()
        self.assertEqual(len(full), TOTAL_MESSAGES)
        self.assertEqual(TOTAL_MESSAGES, 115)
        self.assertEqual(full[0]["message_id"], message_id_for("hr", "hc", 1))

    def test_seed_rebuilds_index_and_summaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "agent.db")
            db.init()
            result = seed_database(db)

            self.assertTrue(result["ok"])
            self.assertEqual(result["messages_seeded"], TOTAL_MESSAGES)
            self.assertEqual(db.stats()["messages"], TOTAL_MESSAGES)
            self.assertTrue(all(db.message_exists(item) for item in GOLDEN_MESSAGE_IDS))

            index = IndexRepository(db).status()
            self.assertTrue(index["indexed"])
            self.assertEqual(index["counts"]["chunks"], 71)
            self.assertEqual(index["counts"]["chunk_messages"], 115)
            self.assertEqual(index["counts"]["entities"], 62)
            self.assertGreater(index["counts"]["edges"], 0)

            summary = SummaryRepository(db, Settings()).status()
            self.assertTrue(summary["built"])
            self.assertGreaterEqual(summary["counts"]["summaries"], 6)
            self.assertEqual(summary["counts"]["messages_covered"], 115)

            status = synthetic_status(db)
            self.assertTrue(status["ready"])
            self.assertFalse(status["missing_golden_references"])

    def test_seed_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "agent.db")
            db.init()
            seed_database(db)
            seed_database(db)

            self.assertEqual(db.stats()["messages"], TOTAL_MESSAGES)
            self.assertTrue(synthetic_status(db)["ready"])


if __name__ == "__main__":
    unittest.main()
