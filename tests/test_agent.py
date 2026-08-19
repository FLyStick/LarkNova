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
from feishu_agent.agent.tools import ToolRegistry
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


def _seed_buns_chat(db: Database) -> None:
    add_chat(db, "oc_a", "知行良知总群")
    db.upsert_message(
        message(
            "m-slogan",
            chat_id="oc_a",
            content="抢业务，抓回款，控成本，提利润。",
            create_time="2026-08-19 07:06:00",
            sender_name="邸晓娟的智能伙伴",
            position=1,
        )
    )
    db.upsert_message(
        message(
            "m-joke",
            chat_id="oc_a",
            content=(
                "☀️ 早安笑话\n\n昨天去买早餐，老板问我要什么馅的包子。"
                "我说：'要个韭菜鸡蛋的。'老板说：'没有。'"
                "老板淡定地说：'有——「你再想想」馅的。'"
            ),
            create_time="2026-08-19 07:10:00",
            sender_name="大管家",
            position=2,
        )
    )
    db.upsert_message(
        message(
            "m-ai-tip",
            chat_id="oc_a",
            content="AI小技巧：用智能体整理会议纪要，效率翻10倍。",
            create_time="2026-08-19 07:11:00",
            sender_name="大管家",
            position=3,
        )
    )
    IndexRepository(db).rebuild(chat_ids=["oc_a"])


def _seed_lunch_chat(db: Database) -> None:
    add_chat(db, "oc_a", "知行良知总群")
    lunch_messages = [
        ("om-low", "老A/小狐狸分享垫资条款等", "2026-08-13 17:06:00"),
        (
            "om-first",
            "通知：明天中午 11:00-13:00 在办公室陪刘琴吃饭，王军陪同",
            "2026-08-13 17:19:00",
        ),
        (
            "om-correct1",
            "更正，明天中午 11:00-13:00 是陪宜宾罗总吃饭",
            "2026-08-13 17:22:00",
        ),
        (
            "om-ask",
            "只有董事长和罗总俩人用餐吗，中等餐标吗",
            "2026-08-13 17:24:00",
        ),
        (
            "om-correct2",
            "又更正，改为陪宜宾罗总吃饭，王军陪同，刘琴取消",
            "2026-08-13 17:27:00",
        ),
        (
            "om-final",
            "最终版：明天中午 11:00-13:00 陪宜宾罗总吃饭，王军陪同，刘琴负责现场保障",
            "2026-08-13 17:28:00",
        ),
        ("om-meal", "订餐标准补充", "2026-08-13 17:28:01"),
        (
            "om-template",
            "大管家 bot 问刘忠培要行程模板",
            "2026-08-13 17:30:00",
        ),
        (
            "om-void",
            "前几条关于明天的通知作废，具体安排以飞书日历为准",
            "2026-08-13 17:33:00",
        ),
        ("om-nobody", "没查到，建议问行政/接待", "2026-08-13 17:35:00"),
    ]
    for position, (message_id, content, create_time) in enumerate(lunch_messages, 1):
        db.upsert_message(
            message(
                message_id,
                chat_id="oc_a",
                content=content,
                create_time=create_time,
                sender_name="大管家",
                position=position,
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


class NoAnswerLlmClient:
    def plan(self, question, chat_ids=None, tool_schema=None):
        return {
            "tools": [
                {
                    "name": "search",
                    "arguments": {
                        "query": "早餐包子什么馅",
                        "limit": 5,
                    },
                }
            ],
            "answer": "",
            "citations": [],
            "input_tokens": 10,
            "output_tokens": 5,
        }


class NoAnswerLunchLlmClient:
    def plan(self, question, chat_ids=None, tool_schema=None):
        return {
            "tools": [
                {
                    "name": "search",
                    "arguments": {
                        "query": "罗总吃饭",
                        "limit": 10,
                    },
                }
            ],
            "answer": "",
            "citations": [],
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

    def test_rule_mode_short_answer_is_extracted_from_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            _seed_buns_chat(db)
            harness = AgentHarness(lambda: db, Settings())

            trace = harness.ask(
                "早餐包子什么馅的，只告诉我包子馅是什么，不需要其他信息",
                mode="rule",
            )

            self.assertEqual(trace.status, "ok")
            self.assertIn("你再想想", trace.answer)
            self.assertNotIn("根据本地消息检索", trace.answer)
            self.assertTrue(trace.citations)

    def test_llm_empty_answer_falls_back_to_concise_synthesis(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            _seed_buns_chat(db)
            harness = AgentHarness(
                lambda: db,
                Settings(),
                llm_client=NoAnswerLlmClient(),
            )

            trace = harness.ask(
                "早餐包子什么馅的，只告诉我包子馅是什么，不需要其他信息",
                mode="llm",
            )

            self.assertEqual(trace.status, "ok")
            self.assertIn("你再想想", trace.answer)
            self.assertNotIn("根据本地工具返回的依据", trace.answer)
            self.assertTrue(trace.degraded)
            self.assertTrue(
                any(step.kind == "synthesize" for step in trace.steps)
            )

    def test_llm_empty_answer_reads_lunch_evidence_and_filters_citations(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            _seed_lunch_chat(db)
            harness = AgentHarness(
                lambda: db,
                Settings(),
                llm_client=NoAnswerLunchLlmClient(),
            )

            trace = harness.ask("什么时候陪罗总吃饭", mode="llm")

            self.assertEqual(trace.status, "ok")
            self.assertIn("11:00", trace.answer)
            self.assertIn("作废", trace.answer)
            self.assertNotIn("根据本地工具返回的依据", trace.answer)
            cited_ids = [item.message_id for item in trace.citations]
            self.assertIn("om-final", cited_ids)
            self.assertIn("om-void", cited_ids)
            self.assertNotIn("om-first", cited_ids)
            self.assertNotIn("om-nobody", cited_ids)

    def test_search_evidence_is_capped_at_message_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = make_db(tmp)
            _seed_buns_chat(db)
            registry = ToolRegistry(lambda: db, Settings())

            result = registry.execute(
                "search",
                {"query": "早餐包子什么馅", "limit": 2},
            )

            self.assertTrue(result.ok)
            self.assertLessEqual(len(result.items), 2)
            self.assertEqual(
                [item["rank"] for item in result.items],
                list(range(1, len(result.items) + 1)),
            )
            self.assertEqual(result.items[0]["rank"], 1)


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
