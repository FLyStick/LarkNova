"""Deterministic rule-mode agent: intent selection, tool calls and refusals."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from feishu_agent.agent.protocol import Citation, ToolCall
from feishu_agent.agent.tools import ToolRegistry, ToolResult
from feishu_agent.config import Settings
from feishu_agent.summary.budget import estimate_tokens


@dataclass
class RuleResult:
    """Output of one deterministic rule-mode answer."""

    intent: str
    answer: str
    status: str = "ok"
    refusal_reason: str = ""
    citations: list[Citation] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens: int = 0
    resolved_chat_ids: list[str] = field(default_factory=list)


class RuleEngine:
    """Resolve a question to one known intent and answer only with evidence."""

    def __init__(self, registry: ToolRegistry, settings: Settings | None = None) -> None:
        self.registry = registry
        self.settings = settings or Settings()
        self._calls: list[ToolCall] = []
        self._citations: list[Citation] = []
        self._seen_message_ids: set[str] = set()
        self._steps = 0
        self._max_steps = max(1, int(self.settings.agent_max_steps))
        self._resolved_chat_ids: list[str] = []

    def answer(
        self,
        question: str,
        chat_ids: list[str] | None = None,
    ) -> RuleResult:
        q = str(question or "").strip()
        self._calls = []
        self._citations = []
        self._seen_message_ids = set()
        self._steps = 0
        self._resolved_chat_ids = [str(item) for item in (chat_ids or [])]
        intent = self._detect_intent(q)

        if intent == "time":
            return self._answer_time(q)
        if intent == "summary":
            return self._answer_summary(q, "summary")
        if intent == "recent":
            return self._answer_recent(q)
        if intent == "graph":
            return self._answer_graph(q)
        return self._answer_search(q)

    def _answer_time(self, question: str) -> RuleResult:
        result = self._run("time_now", {})
        now = (result.raw or {}).get("now") or ""
        answer = f"当前时间：{now}" if result.ok and now else "无法获取当前时间。"
        return self._finalize(
            intent="time",
            question=question,
            answer=answer,
            status="ok",
        )

    def _answer_summary(self, question: str, intent: str) -> RuleResult:
        chats = self._resolve_chats()
        if not chats:
            return self._refuse(intent, "no_chat_scope", "本地库中没有可查询的群聊。")
        lines: list[str] = []
        for chat_id in chats[: self._remaining_steps()]:
            result = self._run("summary", {"chat_id": chat_id})
            if not result.ok:
                continue
            summary = (result.raw or {}).get("summary") or {}
            chat_name = _chat_name_from_items(result.items) or chat_id
            conclusion = str(summary.get("conclusion") or "").strip()
            todo = str(summary.get("todo") or "").strip()
            lines.append(f"群 {chat_name}：{conclusion or '已有摘要'}")
            if todo:
                lines.append(f"  待办：{todo}")
        if lines:
            answer = "结论：\n" + "\n".join(lines)
            return self._finalize(
                intent=intent,
                question=question,
                answer=answer,
                status="ok",
            )
        recent = self._recent_answer(question, chats, intent="summary")
        if recent is not None:
            return recent
        return self._refuse(
            intent,
            "no_summary",
            "本地库中没有已生成的结构化摘要，也没有可引用的最近消息。",
        )

    def _answer_recent(self, question: str) -> RuleResult:
        chats = self._resolve_chats()
        if not chats:
            return self._refuse("recent", "no_chat_scope", "本地库中没有可查询的群聊。")
        recent = self._recent_answer(question, chats, intent="recent")
        if recent is not None:
            return recent
        return self._refuse(
            "recent",
            "no_evidence",
            "本地消息中没有找到与问题相符的依据，暂不回答。",
        )

    def _answer_graph(self, question: str) -> RuleResult:
        keyword = self._extract_keyword(question, graph=True)
        if not keyword:
            return self._refuse("graph", "no_keyword", "无法从问题中识别要查询的实体。")
        result = self._run("graph_entity", {"keyword": keyword})
        if result.ok:
            raw = result.raw or {}
            entity = raw.get("entity") or {}
            neighbors = raw.get("neighbors") or []
            lines = [
                f"实体 {entity.get('value') or entity.get('entity_id') or keyword}：",
                f"类型：{entity.get('entity_type') or '未知'}，共 {len(neighbors)} 个关联实体。",
            ]
            for neighbor in neighbors[:5]:
                edge = neighbor.get("edge_type") or "相关"
                value = neighbor.get("value") or neighbor.get("entity_id") or ""
                lines.append(f"- [{edge}] {value}")
            if result.items:
                lines.append("提及依据：")
                lines.extend(self._item_lines(result.items))
            return self._finalize(
                intent="graph",
                question=question,
                answer="\n".join(lines)[: self.settings.agent_max_answer_chars],
                status="ok",
            )
        search = self._run(
            "search",
            {
                "query": keyword,
                "chat_ids": self._resolved_chat_ids,
                "limit": self.settings.agent_max_evidence_items,
            },
        )
        if search.ok and search.items:
            return self._answer_from_items(
                "graph",
                question,
                search.items,
                "在知识图谱中未命中实体，但消息检索找到以下相关依据：",
            )
        return self._refuse(
            "graph",
            "no_evidence",
            "知识图谱和消息检索都没有找到与问题相符的依据，暂不回答。",
        )

    def _answer_search(self, question: str) -> RuleResult:
        result = self._run(
            "search",
            {
                "query": question,
                "chat_ids": self._resolved_chat_ids,
                "limit": self.settings.agent_max_evidence_items,
            },
        )
        if result.ok and result.items:
            return self._answer_from_items(
                "search",
                question,
                result.items,
                "根据本地消息检索，找到以下相关依据：",
            )
        keyword = self._extract_keyword(question, graph=False)
        chats = self._resolved_chat_ids or self._resolve_chats()
        for chat_id in chats[: max(1, self._remaining_steps())]:
            fallback = self._run(
                "messages",
                {
                    "chat_id": chat_id,
                    "keyword": keyword,
                    "limit": self.settings.agent_max_evidence_items,
                    "order": "desc",
                },
            )
            if fallback.ok and fallback.items:
                return self._answer_from_items(
                    "search",
                    question,
                    fallback.items,
                    "索引未命中，直接按消息记录找到以下相关依据：",
                )
        summary = self._try_summary_fallback(question, chats)
        if summary is not None:
            return summary
        return self._refuse(
            "search",
            "no_evidence",
            "本地消息中没有找到与问题相符的依据，暂不回答。",
        )

    def _recent_answer(
        self,
        question: str,
        chats: list[str],
        *,
        intent: str,
    ) -> RuleResult | None:
        items: list[dict[str, Any]] = []
        for chat_id in chats[: max(1, self._remaining_steps())]:
            result = self._run(
                "messages",
                {
                    "chat_id": chat_id,
                    "limit": self.settings.agent_max_evidence_items,
                    "order": "desc",
                },
            )
            if result.ok and result.items:
                items.extend(result.items)
        if items:
            return self._answer_from_items(
                intent,
                question,
                items,
                "最近消息记录：",
            )
        return None

    def _try_summary_fallback(
        self,
        question: str,
        chats: list[str],
    ) -> RuleResult | None:
        for chat_id in chats[: max(1, self._remaining_steps())]:
            result = self._run("summary", {"chat_id": chat_id})
            if not result.ok:
                continue
            summary = (result.raw or {}).get("summary") or {}
            answer = "根据该群最近的结构化摘要：\n"
            answer += str(summary.get("conclusion") or "暂无结论。")
            todo = str(summary.get("todo") or "").strip()
            if todo:
                answer += "\n待办：" + todo
            return self._finalize(
                intent="search",
                question=question,
                answer=answer[: self.settings.agent_max_answer_chars],
                status="ok",
            )
        return None

    def _answer_from_items(
        self,
        intent: str,
        question: str,
        items: list[dict[str, Any]],
        intro: str,
    ) -> RuleResult:
        selected = items[: self.settings.agent_max_evidence_items]
        if not selected:
            return self._refuse(intent, "no_evidence", "没有可引用的消息依据。")
        lines = [intro]
        lines.extend(self._item_lines(selected))
        selected_ids = {
            str(item.get("message_id") or "") for item in selected if item.get("message_id")
        }
        citations = [
            item
            for item in self._citations
            if item.message_id in selected_ids
        ][: self.settings.agent_max_evidence_items]
        return self._finalize(
            intent=intent,
            question=question,
            answer="\n".join(lines)[: self.settings.agent_max_answer_chars],
            status="ok",
            citations=citations,
        )

    def _item_lines(self, items: list[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        for idx, item in enumerate(items[: self.settings.agent_max_evidence_items], 1):
            when = str(item.get("create_time") or "未知时间")
            who = str(item.get("sender_name") or "未知发送者")
            excerpt = str(item.get("excerpt") or "")
            lines.append(f"{idx}. [{when}] {who}：{excerpt}")
        return lines

    def _finalize(
        self,
        *,
        intent: str,
        question: str,
        answer: str,
        status: str = "ok",
        refusal_reason: str = "",
        citations: list[Citation] | None = None,
    ) -> RuleResult:
        answer = str(answer or "").strip()[: self.settings.agent_max_answer_chars]
        tokens = estimate_tokens(question + "\n" + answer)
        return RuleResult(
            intent=intent,
            answer=answer,
            status=status,
            refusal_reason=refusal_reason,
            citations=list(citations or self._citations),
            tool_calls=list(self._calls),
            tokens=tokens,
            resolved_chat_ids=list(self._resolved_chat_ids),
        )

    def _refuse(self, intent: str, reason: str, detail: str) -> RuleResult:
        return self._finalize(
            intent=intent,
            question="",
            answer=detail,
            status="refused",
            refusal_reason=reason,
            citations=[],
        )

    def _run(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        if self._steps >= self._max_steps:
            return ToolResult(
                False,
                [],
                {"error": "max_steps_exceeded"},
                "max_steps_exceeded",
            )
        call = ToolCall(
            name=name,
            arguments=dict(arguments),
            started_at=_now_iso(),
        )
        started = time.perf_counter()
        result = self.registry.execute(name, arguments)
        call.latency_ms = int((time.perf_counter() - started) * 1000)
        if result.ok:
            call.status = "ok"
            call.result = result.raw
            self._collect_evidence(result)
        else:
            call.status = "error"
            call.error = result.error
            call.result = result.raw
        self._calls.append(call)
        self._steps += 1
        return result

    def _collect_evidence(self, result: ToolResult) -> None:
        for item in result.items:
            message_id = str(item.get("message_id") or "")
            if not message_id or message_id in self._seen_message_ids:
                continue
            self._seen_message_ids.add(message_id)
            self._citations.append(
                Citation(
                    message_id=message_id,
                    chat_id=str(item.get("chat_id") or ""),
                    chat_name=str(item.get("chat_name") or ""),
                    sender_name=str(item.get("sender_name") or ""),
                    create_time=str(item.get("create_time") or ""),
                    excerpt=str(item.get("excerpt") or ""),
                    source=str(item.get("source") or ""),
                    rank=len(self._citations) + 1,
                )
            )

    def _resolve_chats(self) -> list[str]:
        if self._resolved_chat_ids:
            return list(self._resolved_chat_ids)
        result = self._run("chat_list", {})
        if not result.ok:
            return []
        self._resolved_chat_ids = [
            str(item.get("chat_id") or "")
            for item in result.items
            if item.get("chat_id")
        ]
        return list(self._resolved_chat_ids)

    def _remaining_steps(self) -> int:
        return max(1, self._max_steps - self._steps)

    @staticmethod
    def _detect_intent(question: str) -> str:
        text = str(question or "").strip()
        if any(token in text for token in ("现在几点", "几点了", "当前时间", "时间是多少")):
            return "time"
        if any(token in text for token in ("摘要", "总结", "会议纪要", "待办", "发生了什么")):
            return "summary"
        if any(token in text for token in ("实体", "关系", "图谱", "和谁", "关联")):
            return "graph"
        if any(token in text for token in ("最近", "最新", "今天", "昨天", "本周", "刚才")):
            return "recent"
        return "search"

    def _extract_keyword(self, question: str, *, graph: bool) -> str:
        text = str(question or "").strip()
        quoted = re.search(r"[“\"「『]([^”\"」』]+)[”\"」』]?", text)
        if quoted:
            keyword = quoted.group(1).strip()
            return keyword[:24] if keyword else ""
        cleaned = text
        for sep in ("和谁", "有关系", "的关系", "关系", "实体", "图谱"):
            if sep in cleaned:
                cleaned = cleaned.split(sep, 1)[0]
                break
        for token in (
            "请问",
            "一下",
            "最近",
            "最新",
            "谁说过",
            "说了什么",
            "提到",
            "聊到",
            "介绍一下",
            "关于",
            "什么",
            "怎么",
            "如何",
            "为什么",
        ):
            cleaned = cleaned.replace(token, " ")
        cleaned = re.sub(r"[？?。！!，,：:；;、\s]+", " ", cleaned)
        keyword = " ".join(cleaned.split())[:24]
        if graph and not keyword:
            keyword = text[:24]
        return keyword.strip()


def _chat_name_from_items(items: list[dict[str, Any]]) -> str:
    for item in items:
        name = str(item.get("chat_name") or "")
        if name:
            return name
    return ""


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")
