"""Deterministic context building and cheap token estimates for M3."""

from __future__ import annotations

import math
import re
from typing import Any

_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def estimate_tokens(text: Any) -> int:
    """Estimate tokens as CJK chars + ASCII words + half of other chars."""
    value = str(text or "")
    cjk = sum(
        1
        for ch in value
        if "\u3400" <= ch <= "\u4dbf" or "\u4e00" <= ch <= "\u9fff"
    )
    words = _ASCII_TOKEN_RE.findall(value)
    ascii_chars = sum(len(word) for word in words)
    other = max(0, len(value) - cjk - ascii_chars)
    return cjk + len(words) + int(math.ceil(other / 2))


def build_context(
    messages: list[dict[str, Any]],
    max_chars: int = 4000,
) -> list[str]:
    """Return ordered, human-readable message lines capped by max_chars."""
    lines: list[str] = []
    for msg in messages:
        content = str(msg.get("content_normalized") or "").strip()
        if not content:
            continue
        lines.append(_format_message(msg, content))

    budget = max(200, int(max_chars))
    used = 0
    result: list[str] = []
    for line in lines:
        remaining = budget - used
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
    raw_time = str(msg.get("create_time") or "")
    time_part = raw_time[11:19] if len(raw_time) >= 19 else ""
    sender = str(msg.get("sender_name") or "未知").strip() or "未知"
    prefix = f"[{time_part}] {sender}: " if time_part else f"{sender}: "
    return prefix + content
