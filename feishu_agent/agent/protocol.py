"""M4 Agent 执行器的共享数据类型、trace 结构与异常定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class AgentError(RuntimeError):
    """Agent 层的基础异常。"""


class AgentConfigError(AgentError):
    """LLM 模式缺少必要配置时抛出。"""


class AgentGenError(AgentError):
    """LLM 输出无法解析或工具执行失败时抛出。"""


class AgentGuardError(AgentError):
    """安全护栏拦截请求时抛出。"""


@dataclass
class Citation:
    """一条可溯源的引用：指向具体的来源消息或摘要。"""

    message_id: str = ""
    chat_id: str = ""
    chat_name: str = ""
    sender_name: str = ""
    create_time: str = ""
    excerpt: str = ""
    source: str = ""
    rank: int = 1

    def to_dict(self) -> dict[str, Any]:
        """序列化为普通字典，便于保存到 trace JSON。"""
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
        """从字典安全恢复引用对象，缺失字段自动使用默认值。"""
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
    """trace 中记录的一次工具调用。"""

    name: str
    arguments: dict[str, Any]
    status: str = "ok"
    result: Any = None
    error: str = ""
    latency_ms: int = 0
    started_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """序列化为普通字典，便于保存到 trace JSON。"""
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
        """从字典恢复工具调用记录。"""
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
    """Agent trace 中一个可回放的事件节点。"""

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
        """序列化为普通字典，便于保存到 trace JSON。"""
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
        """从字典恢复步骤记录。"""
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
    """一次 ask() 调用的完整结果，持久化后可用于回放与审计。"""

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
        """序列化为普通字典，包含引用和全部步骤。"""
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
        """从字典恢复完整 trace，并重建嵌套的引用与步骤对象。"""
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
    """AgentHarness.ask() 的规范化入参。"""

    question: str
    mode: str = "auto"
    chat_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentRequest":
        """从请求字典构造入参，模式统一转小写并过滤空群 id。"""
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
