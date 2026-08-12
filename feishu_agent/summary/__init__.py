"""M3 AI summary: deterministic baseline and optional LLM upgrade."""

from __future__ import annotations

from feishu_agent.summary.budget import build_context, estimate_tokens
from feishu_agent.summary.factory import make_summarizer
from feishu_agent.summary.protocol import (
    Summarizer,
    SummaryConfigError,
    SummaryGenError,
    SummaryResult,
)
from feishu_agent.summary.repository import SummaryRepository
from feishu_agent.summary.rule_summarizer import RuleSummarizer

__all__ = [
    "RuleSummarizer",
    "Summarizer",
    "SummaryConfigError",
    "SummaryGenError",
    "SummaryRepository",
    "SummaryResult",
    "build_context",
    "estimate_tokens",
    "make_summarizer",
]
