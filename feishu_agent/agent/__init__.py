"""M4 Agent/Harness layer with replayable traces and traceable citations."""

from __future__ import annotations

from feishu_agent.agent.harness import AgentHarness
from feishu_agent.agent.protocol import (
    AgentConfigError,
    AgentError,
    AgentGenError,
    AgentRequest,
    AgentTrace,
    Citation,
)
from feishu_agent.agent.repository import AgentRepository
from feishu_agent.agent.rule_engine import RuleEngine
from feishu_agent.agent.tools import ToolRegistry

__all__ = [
    "AgentConfigError",
    "AgentError",
    "AgentGenError",
    "AgentHarness",
    "AgentRepository",
    "AgentRequest",
    "AgentTrace",
    "Citation",
    "RuleEngine",
    "ToolRegistry",
]
