"""Shared data types for the M4 agent harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class AgentError(RuntimeError):
    """Base error for the agent layer."""


class AgentConfigError(AgentError):
    """Raised when an LLM-backed mode is used without configuration."""


class AgentGenError(AgentError):
    """Raised when LLM output cannot be parsed or tool execution fails."""


class AgentGuardError(AgentError):
    """Raised when a safety guard blocks a request."""


@dataclass
class Citation:
    """One traceable reference to a source message or summary."""

    message_id: str = ""
    chat_id: str = ""
    chat_name: str = ""
    sender_name: str = ""
    create_time: str = ""
    excerpt: str = ""
    source: str = ""
    rank: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "chat_id": self.chat_id,
            "chat_name": self.chat_name,
            "sender_name": self.sender_name,
            "create_time": self.create_time,
            "excerpt": self.excerpt,
            "source": self.source,
            "rank": self.rank,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Citation":
        return cls(
            message_id=str(data.get("message_id") or ""),
            chat_id=str(data.get("chat_id") or ""),
            chat_name=str(data.get("chat_name") or ""),
            sender_name=str(data.get("sender_name") or ""),
            create_time=str(data.get("create_time") or ""),
            excerpt=str(data.get("excerpt") or ""),
            source=str(data.get("source") or ""),
            rank=int(data.get("rank") or 1),
        )


@dataclass
class ToolCall:
    """A single tool invocation recorded inside a trace."""

    name: str
    arguments: dict[str, Any]
    status: str = "ok"
    result: Any = None
    error: str = ""
    latency_ms: int = 0
    started_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "arguments": self.arguments,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "started_at": self.started_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolCall":
        return cls(
            name=str(data.get("name") or ""),
            arguments=data.get("arguments") or {},
            status=str(data.get("status") or "ok"),
            result=data.get("result"),
            error=str(data.get("error") or ""),
            latency_ms=int(data.get("latency_ms") or 0),
            started_at=str(data.get("started_at") or ""),
        )


@dataclass
class AgentStep:
    """One replayable event in an agent trace."""

    seq: int
    kind: str
    status: str = "ok"
    tool: str = ""
    input: Any = None
    output: Any = None
    error: str = ""
    latency_ms: int = 0
    started_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "kind": self.kind,
            "status": self.status,
            "tool": self.tool,
            "input": self.input,
            "output": self.output,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "started_at": self.started_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentStep":
        return cls(
            seq=int(data.get("seq") or 0),
            kind=str(data.get("kind") or ""),
            status=str(data.get("status") or "ok"),
            tool=str(data.get("tool") or ""),
            input=data.get("input"),
            output=data.get("output"),
            error=str(data.get("error") or ""),
            latency_ms=int(data.get("latency_ms") or 0),
            started_at=str(data.get("started_at") or ""),
        )


@dataclass
class AgentTrace:
    """Full result of one ask() call, persisted for replay."""

    trace_id: str
    question: str
    mode: str
    status: str
    answer: str = ""
    refusal_reason: str = ""
    degraded: bool = False
    tokens: int = 0
    latency_ms: int = 0
    chat_ids: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    steps: list[AgentStep] = field(default_factory=list)
    created_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "question": self.question,
            "mode": self.mode,
            "status": self.status,
            "answer": self.answer,
            "refusal_reason": self.refusal_reason,
            "degraded": self.degraded,
            "tokens": self.tokens,
            "latency_ms": self.latency_ms,
            "chat_ids": self.chat_ids,
            "citations": [item.to_dict() for item in self.citations],
            "steps": [item.to_dict() for item in self.steps],
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentTrace":
        return cls(
            trace_id=str(data.get("trace_id") or ""),
            question=str(data.get("question") or ""),
            mode=str(data.get("mode") or "auto"),
            status=str(data.get("status") or "error"),
            answer=str(data.get("answer") or ""),
            refusal_reason=str(data.get("refusal_reason") or ""),
            degraded=bool(data.get("degraded")),
            tokens=int(data.get("tokens") or 0),
            latency_ms=int(data.get("latency_ms") or 0),
            chat_ids=list(data.get("chat_ids") or []),
            citations=[
                Citation.from_dict(item)
                for item in (data.get("citations") or [])
                if isinstance(item, dict)
            ],
            steps=[
                AgentStep.from_dict(item)
                for item in (data.get("steps") or [])
                if isinstance(item, dict)
            ],
            created_at=str(data.get("created_at") or ""),
            finished_at=str(data.get("finished_at") or ""),
        )


@dataclass
class AgentRequest:
    """Normalized input for AgentHarness.ask()."""

    question: str
    mode: str = "auto"
    chat_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentRequest":
        chat_ids = data.get("chat_ids")
        return cls(
            question=str(data.get("question") or ""),
            mode=str(data.get("mode") or "auto").strip().lower(),
            chat_ids=(
                [str(item) for item in chat_ids if str(item).strip()]
                if isinstance(chat_ids, list)
                else []
            ),
        )
