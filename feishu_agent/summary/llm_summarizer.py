"""可选 OpenAI 兼容 LLM 摘要器；默认仍使用规则模式。"""

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
    """调用 OpenAI 兼容的 /chat/completions 接口生成结构化摘要。"""

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
        """组装提示词请求 LLM，并把响应解析为 `SummaryResult`。"""
        started = time.perf_counter()
        # 未配置端点时提前失败，避免运行中途才发现不可用。
        if not self.settings.llm_api_url:
            raise SummaryConfigError(
                "FEISHU_AGENT_LLM_API_URL is empty; configure the endpoint "
                "or use `--mode rule`"
            )
        # 展平所有 chunk 中的消息，保持原始顺序用于上下文构建。
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
        # 提示词显式规定 JSON 字段，降低模型输出结构的漂移概率。
        payload = {
            "model": self.settings.llm_model or "default",
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        # 请求失败不重试，统一转成可诊断的 SummaryGenError。
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.settings.llm_api_url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        if self.settings.llm_api_key:
            # 兼容常见 OpenAI 风格的 Bearer Token 鉴权。
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
            # 模型可能在 JSON 外层再包一层字符串，这里统一做二次解析。
            parsed = json.loads(raw)
            content = parsed["choices"][0]["message"]["content"]
            data = json.loads(content)
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise SummaryGenError(
                f"LLM response is not a valid summary JSON: {exc}"
            ) from exc

        # 用 dict.fromkeys 去重并保持消息首次出现顺序，便于溯源展示。
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
    """把任意字段值规整为去除首尾空白的字符串。"""
    if value is None:
        return ""
    return str(value).strip()


def _string_list(value: Any) -> list[str]:
    """把列表或逗号/换行分隔文本转成去重后的字符串列表。"""
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
    """按中英文逗号与换行拆分成候选条目。"""
    return text.replace("，", "\n").replace(",", "\n").splitlines()
