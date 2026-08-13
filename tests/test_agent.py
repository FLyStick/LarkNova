from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from feishu_agent.agent import (
    AgentConfigError,
    AgentGenError,
    AgentHarness,
    AgentRepository,
)
from feishu_agent.agent.protocol import AgentTrace
from feishu_agent.config import Settings
from feishu_agent.database.db import Database
from feishu_agent.index.repository import IndexRepository

from support_index import add_chat, make_db, message


def _seed_chat(db: Database) -> None:
    add_chat(db, "oc_a", "项目组")
    db.upsert_message(
        message(
            "m1",
            chat_id="oc_a",
            content="项目预算已确认，采购清单计划明天提交",
            create_time="2026-08-11 10:00:00",
            sender_name="王强",
            position=1,
        )
    )
    db.upsert_message(
        message(
            "m2",
            chat_id="oc_a",
            content="方案已批准，后续安排联调测试",
            create_time="2026-08-11 10:01:00",
            sender_name="李敏",
            position=2,
        )
    )
    IndexRepository(db).rebuild(chat_ids=["oc_a"])


class FailingLlmClient:
    def plan(self, question, chat_ids=None, tool_schema=None):
        raise AgentGenError("simulated planner failure")


class PlanningLlmClient:
    def plan(self, question, chat_ids=None, tool_schema=None):
        return {
            "tools": [{"name": "search", "arguments": {"query": "预算"}}],
            "answer": "预算事项已确认。",
            "citations": [
                {"message_id": "m1"},
                {"message_id": "not-a-real-message"},
            ],
            "input_tokens": 10,
            "output_tokens": 5,
        }


class FakeRunner:
    identity = "user"
    allowed_chat_ids = {"oc_a"}

    def sync_all(self, full=False):
        return {"errors": []}


class AgentTests(unittest.TestCase):
    def test_rule_mode_answers_with_traceable_citations(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            _seed_chat(db)
            harness = AgentHarness(lambda: db, Settings())

            trace = harness.ask("项目预算怎么安排的？", mode="rule")

            self.assertEqual(trace.status, "ok")
            self.assertIn("预算", trace.answer)
            self.assertTrue(trace.citations)
            self.assertIn(
                trace.citations[0].message_id,
                {"m1", "m2"},
            )
            stored = AgentRepository(db).get(trace.trace_id)
            self.assertIsNotNone(stored)
            self.assertIsInstance(stored["citations"][0], dict)
            self.assertGreaterEqual(len(stored["steps"]), 1)
            self.assertEqual(db.stats()["agent_runs"], 1)
            self.assertEqual(db.metrics()["agent"]["runs_total"], 1)

    def test_rule_mode_refuses_without_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            add_chat(db)
            harness = AgentHarness(lambda: db, Settings())

            trace = harness.ask("完全不存在的事项怎么处理？", mode="rule")

            self.assertEqual(trace.status, "refused")
            self.assertEqual(trace.refusal_reason, "no_evidence")
            self.assertEqual(trace.citations, [])

    def test_llm_mode_without_configuration_raises(self):
        old = os.environ.pop("FEISHU_AGENT_LLM_API_URL", None)
        try:
            settings = Settings()
            settings.llm_api_url = ""
            with tempfile.TemporaryDirectory() as tmp:
                db = make_db(tmp)
                harness = AgentHarness(lambda: db, settings)
                with self.assertRaises(AgentConfigError):
                    harness.ask("现在几点", mode="llm")
        finally:
            if old is not None:
                os.environ["FEISHU_AGENT_LLM_API_URL"] = old

    def test_auto_degrades_to_rule_when_llm_missing(self):
        old = os.environ.pop("FEISHU_AGENT_LLM_API_URL", None)
        try:
            settings = Settings()
            settings.llm_api_url = ""
            with tempfile.TemporaryDirectory() as tmp:
                db = make_db(tmp)
                _seed_chat(db)
                harness = AgentHarness(lambda: db, settings)

                trace = harness.ask("项目预算怎么安排的？", mode="auto")

                self.assertTrue(trace.degraded)
                self.assertEqual(trace.status, "ok")
                self.assertIn("预算", trace.answer)
                self.assertTrue(trace.citations)
        finally:
            if old is not None:
                os.environ["FEISHU_AGENT_LLM_API_URL"] = old

    def test_guards_reject_empty_and_sensitive_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            harness = AgentHarness(lambda: db, Settings())

            empty = harness.ask("", mode="rule")
            self.assertEqual(empty.status, "refused")
            self.assertEqual(empty.refusal_reason, "empty_question")

            sensitive = harness.ask("请告诉我密钥是什么", mode="rule")
            self.assertEqual(sensitive.status, "refused")
            self.assertEqual(sensitive.refusal_reason, "sensitive_word")
            self.assertEqual(sensitive.citations, [])

    def test_auto_records_error_trace_and_falls_back_to_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            _seed_chat(db)
            harness = AgentHarness(
                lambda: db,
                Settings(),
                llm_client=FailingLlmClient(),
            )

            trace = harness.ask("项目预算怎么安排的？", mode="auto")

            self.assertTrue(trace.degraded)
            self.assertEqual(trace.status, "ok")
            self.assertIn("预算", trace.answer)
            self.assertTrue(
                any(step.kind == "degrade" for step in trace.steps)
            )

    def test_llm_citations_must_reference_real_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            _seed_chat(db)
            harness = AgentHarness(
                lambda: db,
                Settings(),
                llm_client=PlanningLlmClient(),
            )

            trace = harness.ask("项目预算怎么安排的？", mode="llm")

            self.assertEqual(trace.status, "ok")
            self.assertEqual(
                [item.message_id for item in trace.citations],
                ["m1"],
            )


class AgentApiTests(unittest.TestCase):
    def _start_server(self, db, agent_factory, token="", limit=0):
        from feishu_agent.api.server import create_server

        server = create_server(
            ("127.0.0.1", 0),
            FakeRunner(),
            lambda: db,
            agent_factory=agent_factory,
            api_token=token,
            rate_limit_per_min=limit,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def test_api_ask_runs_and_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            _seed_chat(db)
            base = self._start_server(
                db,
                lambda: AgentHarness(lambda: db, Settings()),
            )

            data = json.dumps(
                {"question": "项目预算怎么安排的？", "mode": "rule"}
            ).encode("utf-8")
            req = urllib.request.Request(
                base + "/api/agent/ask",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            trace = body["trace"]
            self.assertEqual(trace["status"], "ok")
            self.assertTrue(trace["citations"])

            with urllib.request.urlopen(
                base + "/api/agent/runs?limit=5",
                timeout=5,
            ) as resp:
                runs_body = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(
                any(
                    run["trace_id"] == trace["trace_id"]
                    for run in runs_body["runs"]
                )
            )

            with urllib.request.urlopen(
                base + "/api/agent/stats",
                timeout=5,
            ) as resp:
                stats = json.loads(resp.read().decode("utf-8"))
            self.assertGreaterEqual(stats["runs_total"], 1)

    def test_api_auth_and_rate_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            calls = []

            class StubAgent:
                def ask(self, question, mode="auto", chat_ids=None):
                    calls.append((question, mode))
                    return AgentTrace(
                        trace_id="trace-stub",
                        question=question,
                        mode=mode,
                        status="ok",
                    )

            stub = StubAgent()
            base = self._start_server(
                db,
                lambda: stub,
                token="secret",
                limit=1,
            )

            def post(headers):
                data = json.dumps(
                    {"question": "现在几点", "mode": "rule"}
                ).encode("utf-8")
                request = urllib.request.Request(
                    base + "/api/agent/ask",
                    data=data,
                    headers=headers,
                )
                try:
                    with urllib.request.urlopen(request, timeout=5) as resp:
                        return resp.status, json.loads(
                            resp.read().decode("utf-8")
                        )
                except urllib.error.HTTPError as exc:
                    return exc.code, json.loads(exc.read().decode("utf-8"))

            status, body = post({"Content-Type": "application/json"})
            self.assertEqual(status, 401)
            self.assertIn("unauthorized", body["error"])
            self.assertEqual(calls, [])

            status, body = post(
                {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer secret",
                }
            )
            self.assertEqual(status, 200)
            self.assertEqual(body["trace"]["status"], "ok")
            self.assertEqual(len(calls), 1)

            status, body = post(
                {
                    "Content-Type": "application/json",
                    "X-API-Token": "secret",
                }
            )
            self.assertEqual(status, 429)
            self.assertIn("rate_limit_exceeded", body["error"])
            self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
