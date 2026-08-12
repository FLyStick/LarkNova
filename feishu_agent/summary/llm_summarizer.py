"""Optional OpenAI-compatible LLM summarizer; rule mode remains the default."""

from __future__ import annotations

import json
import time
import urllib.request
from typing import Any

from feishu_agent.summary.budget import build_context, estimate_tokens
from feishu_agent.summary.protocol import (
    SummaryConfigError,
    SummaryGenError,
    SummaryResult,
)

_SYSTEM_PROMPT = (
    "你负责把飞书群聊片段整理成企业会议纪要式摘要。"
    "只输出 JSON，不要 Markdown，不要额外说明。"
)


class LlmSummarizer:
    """Call an OpenAI-compatible /chat/completions endpoint for summaries."""

    mode = "llm"

    def __init__(self, settings: Any) -> None:
        self.settings = settings

    def summarize_chat(
        self,
        chat_id: str,
        chat_name: str,
        chunks: list[dict[str, Any]],
        now_iso: str,
    ) -> SummaryResult:
        started = time.perf_counter()
        if not self.settings.llm_api_url:
            raise SummaryConfigError(
                "FEISHU_AGENT_LLM_API_URL is empty; configure the endpoint "
                "or use `--mode rule`"
            )
        messages = []
        for chunk in chunks:
            messages.extend(chunk.get("messages") or [])
        context_lines = build_context(
            messages,
            self.settings.summary_max_chars,
        )
        user_prompt = (
            f"群名称：{chat_name or chat_id}\n"
            "请给出 JSON，格式："
            '{"conclusion":"结论","evidence":["依据1"],"todo":["待办1"],'
            '"key_people":["关键人"],"key_dates":["关键日期"],'
            '"entities":["实体"]}\n'
            "对话片段：\n"
            + "\n".join(context_lines)
        )
        payload = {
            "model": self.settings.llm_model or "default",
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
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
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.settings.llm_timeout,
            ) as response:
                raw = response.read().decode("utf-8")
        except Exception as exc:
            raise SummaryGenError(f"LLM request failed: {exc}") from exc

        try:
            parsed = json.loads(raw)
            content = parsed["choices"][0]["message"]["content"]
            data = json.loads(content)
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SummaryGenError(
                f"LLM response is not a valid summary JSON: {exc}"
            ) from exc

        source_message_ids = list(
            dict.fromkeys(str(msg["message_id"]) for msg in messages)
        )
        source_chunk_ids = sorted(
            {int(chunk["id"]) for chunk in chunks if chunk.get("id") is not None}
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        return SummaryResult(
            conclusion=_string(data.get("conclusion")),
            evidence=_string_list(data.get("evidence")),
            todo=_string_list(data.get("todo")),
            key_people=_string_list(data.get("key_people")),
            key_dates=_string_list(data.get("key_dates")),
            entities=_string_list(data.get("entities")),
            source_message_ids=source_message_ids,
            source_chunk_ids=source_chunk_ids,
            input_tokens=estimate_tokens(user_prompt + _SYSTEM_PROMPT),
            output_tokens=estimate_tokens(content),
            latency_ms=latency_ms,
        )


def _string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = [str(item).strip() for item in value]
    else:
        items = [
            part.strip()
            for part in re_split(str(value))
            if part.strip()
        ]
    return list(dict.fromkeys(item for item in items if item))


def re_split(text: str) -> list[str]:
    return text.replace("，", "\n").replace(",", "\n").splitlines()
