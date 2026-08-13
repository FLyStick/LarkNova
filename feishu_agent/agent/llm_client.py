"""Optional OpenAI-compatible LLM planner for the M4 agent harness."""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

from feishu_agent.agent.protocol import AgentConfigError, AgentGenError
from feishu_agent.config import Settings
from feishu_agent.summary.budget import estimate_tokens


_SYSTEM_PROMPT = (
    "你是企业飞书知识 Agent 的规划器。只输出 JSON，不要 Markdown，不要额外说明。"
    "回答必须基于可调用的本地工具，不能编造消息内容。"
)

_OUTPUT_FORMAT = (
    '输出 JSON：{"tools":[{"name":"工具名","arguments":{...}}],'
    '"answer":"最终答案，可在工具执行后填写，也可以留空",'
    '"citations":[{"message_id":"真实消息ID"}]}'
)


class AgentLlmClient:
    """Call an OpenAI-compatible /chat/completions endpoint for plan JSON."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    def plan(
        self,
        question: str,
        *,
        chat_ids: list[str] | None = None,
        tool_schema: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Return a validated planning payload for the harness."""
        if not self.settings.llm_api_url:
            raise AgentConfigError(
                "FEISHU_AGENT_LLM_API_URL is empty; configure the endpoint "
                "or use rule/auto mode"
            )
        user_prompt = self._build_prompt(question, chat_ids, tool_schema)
        payload = {
            "model": self.settings.llm_model or "default",
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        raw = self._post(payload)
        content = self._extract_content(raw)
        data = _extract_json(content, AgentGenError)
        tools = data.get("tools", data.get("tool_calls", data.get("steps", [])))
        if tools is None:
            tools = []
        if not isinstance(tools, list):
            raise AgentGenError("LLM planning response must contain a tools list")
        citations = data.get("citations") or []
        if not isinstance(citations, list):
            raise AgentGenError("LLM planning response citations must be a list")
        answer = str(data.get("answer") or "").strip()
        input_tokens = int(data.get("input_tokens") or 0)
        output_tokens = int(data.get("output_tokens") or 0)
        if not input_tokens and not output_tokens:
            input_tokens = estimate_tokens(user_prompt + _SYSTEM_PROMPT)
            output_tokens = estimate_tokens(content)
        return {
            "tools": tools,
            "answer": answer,
            "citations": citations,
            "raw": data,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }

    def _build_prompt(
        self,
        question: str,
        chat_ids: list[str] | None,
        tool_schema: dict[str, dict[str, Any]] | None,
    ) -> str:
        tools_block = json.dumps(tool_schema or {}, ensure_ascii=False)
        scope = "全部可查询群" if not chat_ids else "、".join(chat_ids[:20])
        return (
            f"问题：{question}\n"
            f"群范围：{scope}\n"
            f"可用工具：{tools_block}\n"
            f"{_OUTPUT_FORMAT}"
        )

    def _post(self, payload: dict[str, Any]) -> str:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.settings.llm_api_url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        if self.settings.llm_api_key:
            request.add_header(
                "Authorization",
                f"Bearer {self.settings.llm_api_key}",
            )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.settings.llm_timeout,
            ) as response:
                raw = response.read().decode("utf-8")
        except Exception as exc:
            raise AgentGenError(f"LLM request failed: {exc}") from exc
        if int((time.perf_counter() - started) * 1000) >= self.settings.llm_timeout * 1000:
            raise AgentGenError("LLM request timed out")
        return raw

    @staticmethod
    def _extract_content(raw: str) -> str:
        try:
            parsed = json.loads(raw)
            content = parsed["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AgentGenError(
                f"LLM response is not a valid chat completion: {exc}"
            ) from exc
        return str(content or "")


def _extract_json(
    content: str,
    error_type: type[AgentGenError],
) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise error_type(
                    f"LLM response is not valid planning JSON: {exc}"
                ) from exc
        else:
            raise error_type("LLM response is not valid planning JSON")
    if not isinstance(data, dict):
        raise error_type("LLM planning response must be a JSON object")
    return data
