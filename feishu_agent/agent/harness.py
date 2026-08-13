"""M4 harness: one ask() path with rule/LLM modes, tool steps and traces."""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any, Callable

from feishu_agent.agent.llm_client import AgentLlmClient
from feishu_agent.agent.protocol import (
    AgentConfigError,
    AgentError,
    AgentGenError,
    AgentStep,
    AgentTrace,
    Citation,
)
from feishu_agent.agent.repository import AgentRepository
from feishu_agent.agent.rule_engine import RuleEngine
from feishu_agent.agent.tools import ToolRegistry
from feishu_agent.config import Settings

_MODES = {"auto", "rule", "llm"}


class AgentHarness:
    """Route one question through guards, tools and a persisted trace."""

    def __init__(
        self,
        db_factory: Callable[[], Any],
        settings: Settings | None = None,
        llm_client: Any | None = None,
    ) -> None:
        self.db_factory = db_factory
        self.settings = settings or Settings()
        self.registry = ToolRegistry(db_factory, self.settings)
        self.rule_engine = RuleEngine(self.registry, self.settings)
        self.llm_client = (
            llm_client if llm_client is not None else AgentLlmClient(self.settings)
        )
        self._uses_custom_llm = llm_client is not None

    def ask(
        self,
        question: str,
        mode: str = "auto",
        chat_ids: list[str] | None = None,
    ) -> AgentTrace:
        started = time.perf_counter()
        created_at = _now_iso()
        question = str(question or "").strip()
        mode = str(mode or "auto").strip().lower()
        chat_ids = _clean_chat_ids(chat_ids)

        guard = self._guard(question, mode, chat_ids)
        if guard is not None:
            return self._record(guard, started)

        if mode == "rule":
            trace = self._run_rule(
                question,
                chat_ids,
                mode="rule",
                created_at=created_at,
            )
        elif mode == "llm":
            if not self._llm_available():
                raise AgentConfigError(
                    "FEISHU_AGENT_LLM_API_URL is empty; configure the endpoint "
                    "or use rule/auto mode"
                )
            try:
                trace = self._run_llm(
                    question,
                    chat_ids,
                    mode="llm",
                    created_at=created_at,
                )
            except AgentGenError as exc:
                trace = self._error_trace(
                    question,
                    mode,
                    chat_ids,
                    created_at,
                    str(exc),
                )
        else:
            trace = self._auto(question, chat_ids, created_at, started)
        return self._record(trace, started)

    def _auto(
        self,
        question: str,
        chat_ids: list[str],
        created_at: str,
        started: float,
    ) -> AgentTrace:
        if not self._llm_available():
            return self._run_rule(
                question,
                chat_ids,
                mode="auto",
                created_at=created_at,
                degraded=True,
                degrade_error="llm not configured",
            )
        try:
            return self._run_llm(
                question,
                chat_ids,
                mode="auto",
                created_at=created_at,
            )
        except AgentError as exc:
            return self._run_rule(
                question,
                chat_ids,
                mode="auto",
                created_at=created_at,
                degraded=True,
                degrade_error=str(exc),
            )

    def _guard(
        self,
        question: str,
        mode: str,
        chat_ids: list[str],
    ) -> AgentTrace | None:
        if mode not in _MODES:
            return self._refuse(
                question,
                mode,
                chat_ids,
                "invalid_mode",
                f"不支持的 mode：{mode}",
            )
        if not question:
            return self._refuse(
                question,
                mode,
                chat_ids,
                "empty_question",
                "问题为空，已拒绝回答。",
            )
        max_chars = int(self.settings.agent_max_question_chars or 0)
        if max_chars > 0 and len(question) > max_chars:
            return self._refuse(
                question,
                mode,
                chat_ids,
                "question_too_long",
                f"问题超过 {max_chars} 字符限制，已拒绝回答。",
            )
        sensitive = [
            word
            for word in (self.settings.agent_sensitive_words or [])
            if word and word.lower() in question.lower()
        ]
        if sensitive:
            return self._refuse(
                question,
                mode,
                chat_ids,
                "sensitive_word",
                "问题包含敏感信息，已拒绝回答。",
            )
        return None

    def _refuse(
        self,
        question: str,
        mode: str,
        chat_ids: list[str],
        reason: str,
        detail: str,
    ) -> AgentTrace:
        now = _now_iso()
        return AgentTrace(
            trace_id=uuid.uuid4().hex,
            question=question,
            mode=mode,
            status="refused",
            answer=detail,
            refusal_reason=reason,
            chat_ids=chat_ids,
            created_at=now,
            finished_at=now,
        )

    def _run_rule(
        self,
        question: str,
        chat_ids: list[str],
        *,
        mode: str,
        created_at: str,
        degraded: bool = False,
        degrade_error: str = "",
    ) -> AgentTrace:
        result = self.rule_engine.answer(question, chat_ids=chat_ids)
        steps: list[AgentStep] = []
        if degrade_error:
            steps.append(
                AgentStep(
                    seq=1,
                    kind="degrade",
                    status="error",
                    input={"from": "llm", "mode": "auto"},
                    output={"error": degrade_error},
                    started_at=created_at,
                )
            )
        seq = len(steps)
        for call in result.tool_calls:
            seq += 1
            steps.append(
                AgentStep(
                    seq=seq,
                    kind="tool",
                    status=call.status,
                    tool=call.name,
                    input=call.arguments,
                    output=call.result,
                    error=call.error,
                    latency_ms=call.latency_ms,
                    started_at=call.started_at,
                )
            )
        return AgentTrace(
            trace_id=uuid.uuid4().hex,
            question=question,
            mode=mode,
            status=result.status,
            answer=result.answer,
            refusal_reason=result.refusal_reason,
            degraded=degraded,
            tokens=result.tokens,
            chat_ids=result.resolved_chat_ids or chat_ids,
            citations=result.citations,
            steps=steps,
            created_at=created_at,
            finished_at=_now_iso(),
        )

    def _run_llm(
        self,
        question: str,
        chat_ids: list[str],
        *,
        mode: str,
        created_at: str,
    ) -> AgentTrace:
        plan = self.llm_client.plan(
            question,
            chat_ids=chat_ids or None,
            tool_schema=self.registry.schema(),
        )
        calls = plan.get("tools") or []
        if not isinstance(calls, list):
            raise AgentGenError("LLM planning response must contain a tools list")
        max_tools = max(1, int(self.settings.agent_max_steps))
        steps: list[AgentStep] = []
        evidence_items: list[dict[str, Any]] = []
        evidence_by_id: dict[str, Citation] = {}
        for seq, item in enumerate(calls[:max_tools], start=1):
            step, result = self._execute_tool(item, seq, created_at)
            steps.append(step)
            if result.ok:
                for evidence in result.items:
                    if not isinstance(evidence, dict):
                        continue
                    evidence_items.append(evidence)
                    message_id = str(evidence.get("message_id") or "")
                    if message_id and message_id not in evidence_by_id:
                        evidence_by_id[message_id] = _citation_from_item(
                            evidence,
                            rank=len(evidence_by_id) + 1,
                        )

        validated: list[Citation] = []
        seen_ids: set[str] = set()
        for item in (plan.get("citations") or []):
            if not isinstance(item, dict):
                continue
            message_id = str(item.get("message_id") or "").strip()
            citation = evidence_by_id.get(message_id)
            if citation is not None and message_id not in seen_ids:
                seen_ids.add(message_id)
                validated.append(citation)

        top_evidence = evidence_items[: self.settings.agent_max_evidence_items]
        answer = str(plan.get("answer") or "").strip()
        if answer and top_evidence:
            citations = validated or [
                _citation_from_item(item, rank=idx)
                for idx, item in enumerate(top_evidence, start=1)
            ]
            status = "ok"
            refusal_reason = ""
        elif answer and not top_evidence:
            answer = "本地工具未返回可引用依据，暂时无法回答。"
            citations = []
            status = "refused"
            refusal_reason = "no_evidence"
        elif top_evidence:
            answer = self._answer_from_items(top_evidence)
            citations = [
                _citation_from_item(item, rank=idx)
                for idx, item in enumerate(top_evidence, start=1)
            ]
            status = "ok"
            refusal_reason = ""
        else:
            answer = "本地工具未返回可引用依据，暂时无法回答。"
            citations = []
            status = "refused"
            refusal_reason = "no_evidence"

        tokens = int(plan.get("input_tokens") or 0) + int(
            plan.get("output_tokens") or 0
        )
        return AgentTrace(
            trace_id=uuid.uuid4().hex,
            question=question,
            mode=mode,
            status=status,
            answer=str(answer)[: self.settings.agent_max_answer_chars],
            refusal_reason=refusal_reason,
            tokens=tokens,
            chat_ids=chat_ids,
            citations=citations[: self.settings.agent_max_evidence_items],
            steps=steps,
            created_at=created_at,
            finished_at=_now_iso(),
        )

    def _error_trace(
        self,
        question: str,
        mode: str,
        chat_ids: list[str],
        created_at: str,
        error: str,
    ) -> AgentTrace:
        step = AgentStep(
            seq=1,
            kind="plan",
            status="error",
            input={"question": question, "mode": mode},
            output={},
            error=error,
            started_at=created_at,
        )
        return AgentTrace(
            trace_id=uuid.uuid4().hex,
            question=question,
            mode=mode,
            status="error",
            answer="",
            refusal_reason="llm_error",
            chat_ids=chat_ids,
            steps=[step],
            created_at=created_at,
            finished_at=_now_iso(),
        )

    def _execute_tool(
        self,
        item: Any,
        seq: int,
        started_at: str,
    ) -> tuple[AgentStep, Any]:
        if not isinstance(item, dict):
            return (
                AgentStep(
                    seq=seq,
                    kind="tool",
                    status="error",
                    tool="",
                    input=item,
                    output=None,
                    error="invalid_tool_call",
                    started_at=started_at,
                ),
                _empty_result(),
            )
        name = str(
            item.get("name")
            or item.get("tool_name")
            or item.get("tool")
            or ""
        ).strip()
        arguments = item.get("arguments", item.get("input", {}))
        if not isinstance(arguments, dict):
            arguments = {}
        tool_started = time.perf_counter()
        result = self.registry.execute(name, arguments)
        latency_ms = int((time.perf_counter() - tool_started) * 1000)
        step = AgentStep(
            seq=seq,
            kind="tool",
            status="ok" if result.ok else "error",
            tool=name,
            input=arguments,
            output=result.to_dict(),
            error=result.error,
            latency_ms=latency_ms,
            started_at=started_at,
        )
        return step, result

    def _answer_from_items(self, items: list[dict[str, Any]]) -> str:
        lines = ["根据本地工具返回的依据："]
        for idx, item in enumerate(
            items[: self.settings.agent_max_evidence_items],
            start=1,
        ):
            when = str(item.get("create_time") or "未知时间")
            who = str(item.get("sender_name") or "未知发送者")
            excerpt = str(item.get("excerpt") or "")
            lines.append(f"{idx}. [{when}] {who}：{excerpt}")
        return "\n".join(lines)[: self.settings.agent_max_answer_chars]

    def _llm_available(self) -> bool:
        return self._uses_custom_llm or bool(self.settings.llm_api_url)

    def _record(self, trace: AgentTrace, started: float) -> AgentTrace:
        trace.finished_at = _now_iso()
        trace.latency_ms = int((time.perf_counter() - started) * 1000)
        db = self.db_factory()
        if hasattr(db, "init"):
            db.init()
        AgentRepository(db).record(trace)
        return trace


def _citation_from_item(item: dict[str, Any], rank: int) -> Citation:
    return Citation(
        message_id=str(item.get("message_id") or ""),
        chat_id=str(item.get("chat_id") or ""),
        chat_name=str(item.get("chat_name") or ""),
        sender_name=str(item.get("sender_name") or ""),
        create_time=str(item.get("create_time") or ""),
        excerpt=str(item.get("excerpt") or ""),
        source=str(item.get("source") or ""),
        rank=int(rank),
    )


def _clean_chat_ids(chat_ids: list[str] | None) -> list[str]:
    if not chat_ids:
        return []
    return [str(item).strip() for item in chat_ids if str(item).strip()]


def _empty_result() -> Any:
    from feishu_agent.agent.tools import ToolResult

    return ToolResult(False, [], {"error": "invalid_tool_call"}, "invalid_tool_call")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")
