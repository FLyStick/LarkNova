"""M3 摘要预算：确定性上下文构建与低成本 token 估算。"""

from __future__ import annotations

import math
import re
from typing import Any

_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def estimate_tokens(text: Any) -> int:
    """按“中文字符 + 英文单词 + 其他字符一半”估算 token 数。"""
    value = str(text or "")
    cjk = sum(
        1
        for ch in value
        if "\u3400" <= ch <= "\u4dbf" or "\u4e00" <= ch <= "\u9fff"
    )
    # 英文部分按完整单词计数，词内的字母不再逐字符累计。
    words = _ASCII_TOKEN_RE.findall(value)
    ascii_chars = sum(len(word) for word in words)
    # 其余符号/标点按约 2 个字符折算 1 个 token。
    other = max(0, len(value) - cjk - ascii_chars)
    return cjk + len(words) + int(math.ceil(other / 2))


def build_context(
    messages: list[dict[str, Any]],
    max_chars: int = 4000,
) -> list[str]:
    """返回有序、可读且受 max_chars 上限约束的消息行。"""
    lines: list[str] = []
    for msg in messages:
        content = str(msg.get("content_normalized") or "").strip()
        if not content:
            continue
        lines.append(_format_message(msg, content))

    # 保留 200 字符下限，避免过小的预算导致上下文完全不可用。
    budget = max(200, int(max_chars))
    used = 0
    result: list[str] = []
    for line in lines:
        remaining = budget - used
        # 单条消息过长时截断并给出标记；剩余空间太小时直接输出截断标记。
        if len(line) > remaining:
            if remaining >= 40:
                result.append(line[:remaining] + " [context truncated]")
            else:
                result.append("[context truncated]")
            break
        result.append(line)
        used += len(line)
    return result


def _format_message(msg: dict[str, Any], content: str) -> str:
    """把消息组装成 `[时间] 发送者: 正文` 的可读行。"""
    raw_time = str(msg.get("create_time") or "")
    time_part = raw_time[11:19] if len(raw_time) >= 19 else ""
    sender = str(msg.get("sender_name") or "未知").strip() or "未知"
    prefix = f"[{time_part}] {sender}: " if time_part else f"{sender}: "
    return prefix + content
