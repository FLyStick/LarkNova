"""摘要生成与持久化的共享类型、协议与异常定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class SummaryConfigError(RuntimeError):
    """使用 LLM 摘要器但缺少必要配置时抛出。"""


class SummaryGenError(RuntimeError):
    """LLM 响应无法解析为合法摘要结构时抛出。"""


@dataclass
class SummaryResult:
    """一次摘要生成返回的结构化结果，含来源与 token 统计。"""

    conclusion: str
    evidence: list[str]
    todo: list[str]
    key_people: list[str]
    key_dates: list[str]
    entities: list[str]
    source_message_ids: list[str]
    source_chunk_ids: list[int]
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0

    def to_structure(self) -> dict[str, Any]:
        """返回用于落库与展示的 JSON 结构字段。"""
        return {
            "conclusion": self.conclusion,
            "evidence": self.evidence,
            "todo": self.todo,
            "key_people": self.key_people,
            "key_dates": self.key_dates,
            "entities": self.entities,
        }


class Summarizer(Protocol):
    """摘要器统一接口：按群聊块生成结构化摘要。"""

    mode: str

    def summarize_chat(
        self,
        chat_id: str,
        chat_name: str,
        chunks: list[dict[str, Any]],
        now_iso: str,
    ) -> SummaryResult:
        """为一个群聊的已索引消息构建结构化摘要。"""
