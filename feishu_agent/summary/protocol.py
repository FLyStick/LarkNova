"""Shared types for summary generation and persistence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class SummaryConfigError(RuntimeError):
    """Raised when an LLM-backed summarizer is used without configuration."""


class SummaryGenError(RuntimeError):
    """Raised when an LLM response cannot be parsed into a summary."""


@dataclass
class SummaryResult:
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
        return {
            "conclusion": self.conclusion,
            "evidence": self.evidence,
            "todo": self.todo,
            "key_people": self.key_people,
            "key_dates": self.key_dates,
            "entities": self.entities,
        }


class Summarizer(Protocol):
    mode: str

    def summarize_chat(
        self,
        chat_id: str,
        chat_name: str,
        chunks: list[dict[str, Any]],
        now_iso: str,
    ) -> SummaryResult:
        """Build a structured summary for one chat's indexed messages."""
