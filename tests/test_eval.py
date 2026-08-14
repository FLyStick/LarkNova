from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from feishu_agent.config import Settings
from feishu_agent.database.db import Database
from feishu_agent.eval import (
    EvalRunner,
    GOLDEN_CASES,
    dump_golden,
    load_golden,
)
from feishu_agent.synthetic import TOTAL_MESSAGES, seed_database


class GoldenFileTests(unittest.TestCase):
    def test_golden_dump_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "golden.json"
            dump_golden(path)
            cases = load_golden(path)
            self.assertEqual(len(cases), len(GOLDEN_CASES))
            self.assertEqual(
                [case.id for case in cases],
                [case.id for case in GOLDEN_CASES],
            )
            self.assertEqual(len(GOLDEN_CASES), 41)


class EvalRunnerTests(unittest.TestCase):
    def test_full_golden_run_passes_on_synthetic_corpus(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "agent.db")
            db.init()
            seed = seed_database(db)
            self.assertEqual(seed["messages_seeded"], TOTAL_MESSAGES)

            report = EvalRunner(lambda: db, Settings()).run(mode="rule")

            self.assertEqual(report["total"], len(GOLDEN_CASES))
            self.assertEqual(report["passed"], len(GOLDEN_CASES))
            self.assertEqual(report["accuracy"], 1.0)
            metrics = report["metrics"]
            self.assertIn("reference_citation_rate", metrics)
            self.assertIn("keyword_hit_rate", metrics)
            self.assertIn("p95_latency_ms", metrics)
            self.assertEqual(set(metrics["by_type"].keys()), {
                "graph",
                "recent",
                "refusal",
                "search",
                "summary",
            })


if __name__ == "__main__":
    unittest.main()
