"""摘要生成器工厂：按配置模式返回规则或 LLM 实现。"""

from __future__ import annotations

from typing import Any

from feishu_agent.summary.llm_summarizer import LlmSummarizer
from feishu_agent.summary.protocol import SummaryConfigError
from feishu_agent.summary.rule_summarizer import RuleSummarizer


def make_summarizer(mode: str, settings: Any) -> Any:
    """根据配置模式返回规则摘要器或 LLM 摘要器。"""
    normalized = (mode or "rule").strip().lower()
    if normalized == "rule":
        return RuleSummarizer(settings)
    if normalized == "llm":
        return LlmSummarizer(settings)
    raise SummaryConfigError(
        f"unknown summary mode {mode!r}; expected rule or llm"
    )
